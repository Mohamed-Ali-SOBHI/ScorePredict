from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    log_loss,
    precision_recall_fscore_support,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inference.portfolio_presets import PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
from train.ml_common import (
    build_draw_binary_xgb_model,
    build_xgb_model,
    get_feature_cols,
    make_draw_target,
    make_sample_weight,
)


LABELS = np.array([0, 1, 2], dtype=int)
LABEL_NAMES = ("away", "draw", "home")
MARKET_PROBABILITY_COLUMNS = (
    "market_away_prob_open",
    "market_draw_prob_open",
    "market_home_prob_open",
)
VARIANTS = (
    "current",
    "unweighted",
    "soft_class_weight",
    "recency_decay_0_80",
    "rolling_5_seasons",
    "alternate_scope",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare production-model challengers with strict rolling-origin evaluation."
    )
    parser.add_argument("--dataset", default="train/dataset_home.csv")
    parser.add_argument("--first-test-season", type=int, default=2017)
    parser.add_argument("--last-test-season", type=int, default=2025)
    parser.add_argument(
        "--output",
        default="train/output/model_challenger_evaluation_2017_2025.json",
    )
    parser.add_argument(
        "--latest-holdout-only",
        action="store_true",
        help="Only run the final val-2024/test-2025 holdout and append it to an existing report.",
    )
    return parser.parse_args()


def normalized_probabilities(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), 1e-8, 1.0)
    return clipped / clipped.sum(axis=1, keepdims=True)


def temperature_scale(values: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(values, 1e-8, 1.0)) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    scaled = np.exp(logits)
    return scaled / scaled.sum(axis=1, keepdims=True)


def top_label_ece(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    confidence = probabilities.max(axis=1)
    prediction = probabilities.argmax(axis=1)
    correct = (prediction == y_true).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for index in range(bins):
        if index == bins - 1:
            mask = (confidence >= edges[index]) & (confidence <= edges[index + 1])
        else:
            mask = (confidence >= edges[index]) & (confidence < edges[index + 1])
        if mask.any():
            result += float(mask.mean()) * abs(float(correct[mask].mean() - confidence[mask].mean()))
    return float(result)


def prediction_metrics(frame: pd.DataFrame) -> dict:
    y_true = frame["target"].to_numpy(dtype=int)
    probabilities = normalized_probabilities(
        frame[["p_away", "p_draw", "p_home"]].to_numpy(dtype=float)
    )
    prediction = probabilities.argmax(axis=1)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, prediction, labels=LABELS, zero_division=0
    )
    one_hot = np.eye(3, dtype=float)[y_true]
    return {
        "matches": int(len(frame)),
        "accuracy": float(accuracy_score(y_true, prediction)),
        "macro_f1": float(np.mean(f1)),
        "log_loss": float(log_loss(y_true, probabilities, labels=LABELS)),
        "brier_multiclass": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "top_label_ece": top_label_ece(y_true, probabilities),
        "classes": {
            name: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
            }
            for index, name in enumerate(LABEL_NAMES)
        },
    }


def model_configurations():
    configurations = []
    strategy_to_model = {}
    key_to_model = {}
    for strategy in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026:
        key = (
            strategy.train_league,
            strategy.bet_league,
            strategy.n_estimators,
            tuple(sorted(strategy.params.items())),
        )
        if key not in key_to_model:
            model_id = f"model_{len(configurations) + 1}_{strategy.bet_league.lower()}"
            key_to_model[key] = model_id
            configurations.append((model_id, strategy))
        strategy_to_model[strategy.name] = key_to_model[key]
    return configurations, strategy_to_model


def training_rows(dataset: pd.DataFrame, strategy, season: int, variant: str) -> pd.DataFrame:
    rows = dataset[dataset["season"] < season].copy()
    train_league = strategy.train_league
    if variant == "alternate_scope":
        train_league = "" if train_league else strategy.bet_league
    if train_league:
        rows = rows[rows["league"] == train_league].copy()
    if variant == "rolling_5_seasons":
        rows = rows[rows["season"] >= season - 5].copy()
    return rows


def sample_weights(train: pd.DataFrame, y: pd.Series, season: int, variant: str) -> np.ndarray | None:
    if variant == "unweighted":
        return None
    base = make_sample_weight(y).to_numpy(dtype=float)
    if variant == "soft_class_weight":
        base = np.sqrt(base)
    if variant == "recency_decay_0_80":
        ages = (season - 1 - train["season"].to_numpy(dtype=float)).clip(min=0)
        base *= np.power(0.80, ages)
    return base / np.mean(base)


def fit_predict_variant(
    dataset: pd.DataFrame,
    strategy,
    season: int,
    variant: str,
) -> tuple[pd.DataFrame, dict]:
    train = training_rows(dataset, strategy, season, variant)
    test = dataset[
        (dataset["season"] == season) & (dataset["league"] == strategy.bet_league)
    ].copy()
    if train.empty or test.empty:
        return pd.DataFrame(), {}

    feature_cols = get_feature_cols(train, include_draw_features=False)
    draw_feature_cols = get_feature_cols(train, include_draw_features=True)
    y_train = train["target"].astype(int)
    multiclass = build_xgb_model(
        seed=42,
        n_estimators=strategy.n_estimators,
        **strategy.params,
    )
    weights = sample_weights(train, y_train, season, variant)
    multiclass.fit(train[feature_cols], y_train, sample_weight=weights)
    probabilities = normalized_probabilities(multiclass.predict_proba(test[feature_cols]))

    y_draw = make_draw_target(y_train)
    binary = build_draw_binary_xgb_model(
        seed=42,
        n_estimators=strategy.n_estimators,
        **strategy.params,
    )
    draw_weights = sample_weights(train, y_draw, season, variant)
    binary.fit(train[draw_feature_cols], y_draw, sample_weight=draw_weights)
    binary_probability = binary.predict_proba(test[draw_feature_cols])[:, 1]

    result = test[
        [
            "match_id",
            "date",
            "season",
            "league",
            "target",
            "market_away_win_odds_open",
            "market_draw_odds_open",
            "market_home_win_odds_open",
            *MARKET_PROBABILITY_COLUMNS,
        ]
    ].copy()
    result[["p_away", "p_draw", "p_home"]] = probabilities
    result["p_binary_draw"] = binary_probability
    result["variant"] = variant
    return result, {
        "train_rows": int(len(train)),
        "train_min_season": int(train["season"].min()),
        "train_max_season": int(train["season"].max()),
    }


def fit_predict_fixed_holdout(
    dataset: pd.DataFrame,
    strategy,
    variant: str,
    *,
    validation_season: int,
    test_season: int,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict]:
    train = training_rows(dataset, strategy, validation_season, variant)
    score = dataset[
        dataset["season"].isin([validation_season, test_season])
        & (dataset["league"] == strategy.bet_league)
    ].copy()
    if train.empty or score.empty:
        return pd.DataFrame(), {}

    feature_cols = get_feature_cols(train, include_draw_features=False)
    draw_feature_cols = get_feature_cols(train, include_draw_features=True)
    y_train = train["target"].astype(int)
    multiclass = build_xgb_model(
        seed=seed,
        n_estimators=strategy.n_estimators,
        **strategy.params,
    )
    weights = sample_weights(train, y_train, validation_season, variant)
    multiclass.fit(train[feature_cols], y_train, sample_weight=weights)
    probabilities = normalized_probabilities(multiclass.predict_proba(score[feature_cols]))

    y_draw = make_draw_target(y_train)
    binary = build_draw_binary_xgb_model(
        seed=seed,
        n_estimators=strategy.n_estimators,
        **strategy.params,
    )
    draw_weights = sample_weights(train, y_draw, validation_season, variant)
    binary.fit(train[draw_feature_cols], y_draw, sample_weight=draw_weights)
    binary_probability = binary.predict_proba(score[draw_feature_cols])[:, 1]

    result = score[
        [
            "match_id",
            "date",
            "season",
            "league",
            "target",
            "market_away_win_odds_open",
            "market_draw_odds_open",
            "market_home_win_odds_open",
            *MARKET_PROBABILITY_COLUMNS,
        ]
    ].copy()
    result[["p_away", "p_draw", "p_home"]] = probabilities
    result["p_binary_draw"] = binary_probability
    result["variant"] = variant
    return result, {
        "train_rows": int(len(train)),
        "train_min_season": int(train["season"].min()),
        "train_max_season": int(train["season"].max()),
        "validation_season": validation_season,
        "test_season": test_season,
        "seed": seed,
    }


def build_postprocessed_predictions(raw: pd.DataFrame, first_test_season: int) -> pd.DataFrame:
    current = raw[raw["variant"] == "current"].copy()
    output = []
    temperatures = np.array([0.60, 0.75, 0.90, 1.00, 1.10, 1.25, 1.50, 1.75, 2.00])
    alphas = np.linspace(0.0, 1.0, 21)

    for season in sorted(current["season"].unique()):
        season = int(season)
        if season < first_test_season:
            continue
        validation = current[current["season"] == season - 1].copy()
        test = current[current["season"] == season].copy()
        if validation.empty or test.empty:
            continue

        val_y = validation["target"].to_numpy(dtype=int)
        val_model = normalized_probabilities(
            validation[["p_away", "p_draw", "p_home"]].to_numpy(dtype=float)
        )
        val_market = normalized_probabilities(
            validation[list(MARKET_PROBABILITY_COLUMNS)].to_numpy(dtype=float)
        )
        test_model = normalized_probabilities(
            test[["p_away", "p_draw", "p_home"]].to_numpy(dtype=float)
        )
        test_market = normalized_probabilities(
            test[list(MARKET_PROBABILITY_COLUMNS)].to_numpy(dtype=float)
        )

        best_temperature = min(
            temperatures,
            key=lambda value: log_loss(
                val_y, temperature_scale(val_model, float(value)), labels=LABELS
            ),
        )
        val_temperature = temperature_scale(val_model, float(best_temperature))
        test_temperature = temperature_scale(test_model, float(best_temperature))

        best_alpha = min(
            alphas,
            key=lambda value: log_loss(
                val_y,
                normalized_probabilities(float(value) * val_temperature + (1.0 - float(value)) * val_market),
                labels=LABELS,
            ),
        )
        test_blend = normalized_probabilities(
            float(best_alpha) * test_temperature + (1.0 - float(best_alpha)) * test_market
        )

        calibrator = LogisticRegression(C=1.0, max_iter=2000)
        calibrator.fit(np.log(np.clip(val_model, 1e-8, 1.0)), val_y)
        calibrated = normalized_probabilities(
            calibrator.predict_proba(np.log(np.clip(test_model, 1e-8, 1.0)))
        )

        stacker = LogisticRegression(C=1.0, max_iter=2000)
        stacker.fit(
            np.column_stack(
                [
                    np.log(np.clip(val_model, 1e-8, 1.0)),
                    np.log(np.clip(val_market, 1e-8, 1.0)),
                ]
            ),
            val_y,
        )
        stacked = normalized_probabilities(
            stacker.predict_proba(
                np.column_stack(
                    [
                        np.log(np.clip(test_model, 1e-8, 1.0)),
                        np.log(np.clip(test_market, 1e-8, 1.0)),
                    ]
                )
            )
        )

        binary_calibrator = LogisticRegression(C=1.0, max_iter=2000)
        val_binary = np.clip(validation["p_binary_draw"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        test_binary = np.clip(test["p_binary_draw"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        binary_calibrator.fit(
            np.log(val_binary / (1.0 - val_binary)).reshape(-1, 1),
            (val_y == 1).astype(int),
        )
        test_binary_calibrated = binary_calibrator.predict_proba(
            np.log(test_binary / (1.0 - test_binary)).reshape(-1, 1)
        )[:, 1]

        variants = {
            "temperature_calibrated": test_temperature,
            "market_blend": test_blend,
            "probability_calibrated": calibrated,
            "market_correction_stacker": stacked,
        }
        for name, probabilities in variants.items():
            variant_frame = test.copy()
            variant_frame[["p_away", "p_draw", "p_home"]] = probabilities
            variant_frame["p_binary_draw"] = test_binary_calibrated
            variant_frame["variant"] = name
            variant_frame["selected_temperature"] = float(best_temperature)
            variant_frame["selected_model_weight"] = float(best_alpha)
            output.append(variant_frame)

    if not output:
        return pd.DataFrame(columns=raw.columns)
    return pd.concat(output, ignore_index=True)


def market_predictions(raw: pd.DataFrame, first_test_season: int) -> pd.DataFrame:
    base = raw[
        (raw["variant"] == "current") & (raw["season"] >= first_test_season)
    ].copy()
    probabilities = normalized_probabilities(base[list(MARKET_PROBABILITY_COLUMNS)].to_numpy())
    base[["p_away", "p_draw", "p_home"]] = probabilities
    base["p_binary_draw"] = probabilities[:, 1]
    base["variant"] = "market_only"
    return base


def draw_override_predictions(frame: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    # Tune a draw decision threshold on the immediately preceding season only.
    result = []
    current = raw[raw["variant"] == "current"]
    for season in sorted(frame["season"].unique()):
        test = frame[frame["season"] == season].copy()
        previous = current[current["season"] == int(season) - 1].copy()
        if previous.empty or test.empty:
            continue
        previous_probability = np.minimum(
            previous["p_draw"].to_numpy(dtype=float),
            previous["p_binary_draw"].to_numpy(dtype=float),
        )
        previous_base = previous[["p_away", "p_draw", "p_home"]].to_numpy().argmax(axis=1)
        y_previous = previous["target"].to_numpy(dtype=int)
        thresholds = np.linspace(0.15, 0.50, 36)

        def threshold_score(threshold: float) -> float:
            prediction = previous_base.copy()
            prediction[previous_probability >= threshold] = 1
            _, _, f1, _ = precision_recall_fscore_support(
                y_previous, prediction, labels=LABELS, zero_division=0
            )
            return float(np.mean(f1))

        threshold = max(thresholds, key=threshold_score)
        probabilities = test[["p_away", "p_draw", "p_home"]].to_numpy(dtype=float)
        draw_signal = np.minimum(
            probabilities[:, 1], test["p_binary_draw"].to_numpy(dtype=float)
        )
        # Encoding the override into probabilities keeps the standard metric path.
        override = probabilities.copy()
        selected = draw_signal >= threshold
        override[selected, 1] = np.maximum(override[selected].max(axis=1) + 1e-4, override[selected, 1])
        override = normalized_probabilities(override)
        test[["p_away", "p_draw", "p_home"]] = override
        test["variant"] = "draw_specialist_override"
        test["selected_draw_threshold"] = float(threshold)
        result.append(test)
    return pd.concat(result, ignore_index=True) if result else pd.DataFrame(columns=frame.columns)


def maximum_drawdown(profits: np.ndarray) -> float:
    cumulative = np.cumsum(np.asarray(profits, dtype=float))
    if cumulative.size == 0:
        return 0.0
    running_peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    return float(np.min(cumulative - running_peak))


def betting_metrics(bets: pd.DataFrame) -> dict:
    if bets.empty:
        return {
            "bets": 0,
            "profit_units": 0.0,
            "roi": None,
            "hit_rate": None,
            "average_odds": None,
            "positive_seasons": 0,
            "tested_seasons": 0,
            "max_drawdown_units": 0.0,
            "roi_ci_low": None,
            "roi_ci_high": None,
            "bootstrap_probability_roi_positive": None,
            "by_season": {},
        }
    ordered = bets.sort_values(["date", "match_id"]).copy()
    ordered["won"] = ordered["target"].astype(int) == 1
    ordered["profit"] = np.where(ordered["won"], ordered["selected_odds"] - 1.0, -1.0)
    profit_values = ordered["profit"].to_numpy(dtype=float)
    rng = np.random.default_rng(20260901)
    bootstrap_roi = profit_values[
        rng.integers(0, len(profit_values), size=(5000, len(profit_values)))
    ].mean(axis=1)
    by_season = {}
    for season, part in ordered.groupby("season", sort=True):
        profit = float(part["profit"].sum())
        by_season[str(int(season))] = {
            "bets": int(len(part)),
            "profit_units": profit,
            "roi": float(profit / len(part)),
        }
    return {
        "bets": int(len(ordered)),
        "profit_units": float(ordered["profit"].sum()),
        "roi": float(ordered["profit"].mean()),
        "hit_rate": float(ordered["won"].mean()),
        "average_odds": float(ordered["selected_odds"].mean()),
        "positive_seasons": int(sum(item["profit_units"] > 0 for item in by_season.values())),
        "tested_seasons": int(len(by_season)),
        "max_drawdown_units": maximum_drawdown(ordered["profit"].to_numpy()),
        "roi_ci_low": float(np.quantile(bootstrap_roi, 0.025)),
        "roi_ci_high": float(np.quantile(bootstrap_roi, 0.975)),
        "bootstrap_probability_roi_positive": float(np.mean(bootstrap_roi > 0.0)),
        "by_season": by_season,
    }


def select_portfolio_bets(
    predictions: pd.DataFrame,
    strategy_to_model: dict[str, str],
    variant: str,
) -> pd.DataFrame:
    selected = []
    variant_rows = predictions[predictions["variant"] == variant]
    for strategy in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026:
        rows = variant_rows[variant_rows["model_id"] == strategy_to_model[strategy.name]].copy()
        if rows.empty:
            continue
        draw_odds = rows["market_draw_odds_open"].to_numpy(dtype=float)
        draw_probability = np.minimum(
            rows["p_draw"].to_numpy(dtype=float),
            rows["p_binary_draw"].to_numpy(dtype=float),
        )
        market_draw = rows["market_draw_prob_open"].to_numpy(dtype=float)
        market = rows[list(MARKET_PROBABILITY_COLUMNS)].to_numpy(dtype=float)
        is_market_favorite = market.argmax(axis=1) == 1
        edge = draw_probability - market_draw
        expected_value = draw_probability * draw_odds - 1.0
        mask = (
            (expected_value > strategy.threshold)
            & (edge >= strategy.edge_min)
            & (draw_odds >= strategy.odds_min)
            & (draw_odds < strategy.odds_max)
        )
        if strategy.market_favorite_mode == "nonfavorite":
            mask &= ~is_market_favorite
        elif strategy.market_favorite_mode == "favorite":
            mask &= is_market_favorite
        chosen = rows.loc[mask].copy()
        chosen["selected_odds"] = draw_odds[mask]
        chosen["expected_value"] = expected_value[mask]
        chosen["strategy_name"] = strategy.name
        selected.append(chosen)
    if not selected:
        return pd.DataFrame()
    bets = pd.concat(selected, ignore_index=True)
    bets = bets.sort_values(["date", "expected_value"], ascending=[True, False])
    return bets.drop_duplicates(subset=["match_id"], keep="first")


def scored_draw_rows(rows: pd.DataFrame) -> pd.DataFrame:
    scored = rows.copy()
    scored["selected_odds"] = scored["market_draw_odds_open"].astype(float)
    scored["predicted_probability"] = np.minimum(
        scored["p_draw"].to_numpy(dtype=float),
        scored["p_binary_draw"].to_numpy(dtype=float),
    )
    scored["market_probability"] = scored["market_draw_prob_open"].astype(float)
    scored["edge"] = scored["predicted_probability"] - scored["market_probability"]
    scored["expected_value"] = scored["predicted_probability"] * scored["selected_odds"] - 1.0
    market = scored[list(MARKET_PROBABILITY_COLUMNS)].to_numpy(dtype=float)
    scored["bet_is_market_favorite"] = market.argmax(axis=1) == 1
    return scored


def tune_filters_on_validation(
    predictions: pd.DataFrame,
    strategy_to_model: dict[str, str],
    variant: str,
    *,
    validation_season: int,
    test_season: int,
) -> dict:
    variant_rows = predictions[predictions["variant"] == variant]
    selected_test_frames = []
    selected_rules = []
    thresholds = np.arange(0.05, 0.551, 0.05)
    edge_values = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)

    for strategy in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026:
        model_rows = variant_rows[
            variant_rows["model_id"] == strategy_to_model[strategy.name]
        ]
        validation = scored_draw_rows(model_rows[model_rows["season"] == validation_season])
        test = scored_draw_rows(model_rows[model_rows["season"] == test_season])
        if validation.empty or test.empty:
            continue

        def static_mask(frame: pd.DataFrame) -> np.ndarray:
            mask = (
                (frame["selected_odds"].to_numpy() >= strategy.odds_min)
                & (frame["selected_odds"].to_numpy() < strategy.odds_max)
            )
            if strategy.market_favorite_mode == "nonfavorite":
                mask &= ~frame["bet_is_market_favorite"].to_numpy(dtype=bool)
            elif strategy.market_favorite_mode == "favorite":
                mask &= frame["bet_is_market_favorite"].to_numpy(dtype=bool)
            return mask

        validation_static = static_mask(validation)
        best = None
        for threshold in thresholds:
            for edge_min in edge_values:
                mask = (
                    validation_static
                    & (validation["expected_value"].to_numpy() > threshold)
                    & (validation["edge"].to_numpy() >= edge_min)
                )
                chosen = validation.loc[mask].copy()
                if len(chosen) < 20:
                    continue
                won = chosen["target"].to_numpy(dtype=int) == 1
                profits = np.where(won, chosen["selected_odds"].to_numpy(dtype=float) - 1.0, -1.0)
                roi = float(profits.mean())
                profit = float(profits.sum())
                if roi < 0.02:
                    continue
                rank = (roi, profit, len(chosen))
                if best is None or rank > best["rank"]:
                    best = {
                        "rank": rank,
                        "threshold": float(threshold),
                        "edge_min": float(edge_min),
                        "validation": {
                            "bets": int(len(chosen)),
                            "profit_units": profit,
                            "roi": roi,
                            "hit_rate": float(won.mean()),
                        },
                    }
        if best is None:
            selected_rules.append(
                {
                    "strategy_name": strategy.name,
                    "selected": False,
                    "reason": "no_validation_setting_met_minimums",
                }
            )
            continue

        test_mask = (
            static_mask(test)
            & (test["expected_value"].to_numpy() > best["threshold"])
            & (test["edge"].to_numpy() >= best["edge_min"])
        )
        chosen_test = test.loc[test_mask].copy()
        chosen_test["strategy_name"] = strategy.name
        selected_test_frames.append(chosen_test)
        selected_rules.append(
            {
                "strategy_name": strategy.name,
                "selected": True,
                "threshold": best["threshold"],
                "edge_min": best["edge_min"],
                "validation": best["validation"],
                "test_before_portfolio_dedupe": betting_metrics(chosen_test),
            }
        )

    if selected_test_frames:
        test_bets = pd.concat(selected_test_frames, ignore_index=True)
        test_bets = test_bets.sort_values(
            ["match_id", "expected_value", "edge"], ascending=[True, False, False]
        ).drop_duplicates(subset=["match_id"], keep="first")
    else:
        test_bets = pd.DataFrame()
    return {
        "test": betting_metrics(test_bets),
        "selected_rules": selected_rules,
    }


def latest_holdout_report(
    dataset: pd.DataFrame,
    configurations,
    strategy_to_model: dict[str, str],
    *,
    validation_season: int = 2024,
    test_season: int = 2025,
) -> dict:
    frames = []
    audit_rows = []
    for model_id, strategy in configurations:
        seed_frames = []
        for variant in VARIANTS:
            frame, audit = fit_predict_fixed_holdout(
                dataset,
                strategy,
                variant,
                validation_season=validation_season,
                test_season=test_season,
            )
            if frame.empty:
                continue
            frame["model_id"] = model_id
            frames.append(frame)
            if variant == "current":
                seed_frames.append(frame.copy())
            audit_rows.append({"model_id": model_id, "variant": variant, **audit})

        research_frame, research_audit = fit_predict_fixed_holdout(
            dataset,
            strategy,
            "current",
            validation_season=validation_season,
            test_season=test_season,
            seed=7066,
        )
        research_frame["model_id"] = model_id
        research_frame["variant"] = "research_seed_7066"
        frames.append(research_frame)
        seed_frames.append(research_frame.copy())
        audit_rows.append(
            {"model_id": model_id, "variant": "research_seed_7066", **research_audit}
        )

        for ensemble_seed in (73, 2026, 31415):
            seed_frame, seed_audit = fit_predict_fixed_holdout(
                dataset,
                strategy,
                "current",
                validation_season=validation_season,
                test_season=test_season,
                seed=ensemble_seed,
            )
            seed_frame["model_id"] = model_id
            seed_frames.append(seed_frame)
            audit_rows.append(
                {
                    "model_id": model_id,
                    "variant": f"seed_ensemble_member_{ensemble_seed}",
                    **seed_audit,
                }
            )

        ensemble = seed_frames[0].copy()
        probability_columns = ["p_away", "p_draw", "p_home", "p_binary_draw"]
        for column in probability_columns:
            ensemble[column] = np.mean(
                [member[column].to_numpy(dtype=float) for member in seed_frames],
                axis=0,
            )
        ensemble["variant"] = "seed_ensemble_5"
        frames.append(ensemble)
        print(f"finished holdout model={model_id}", flush=True)

    raw = pd.concat(frames, ignore_index=True)
    postprocessed = build_postprocessed_predictions(raw, test_season)
    market = market_predictions(raw, test_season)
    evaluated = pd.concat([raw, postprocessed, market], ignore_index=True, sort=False)
    evaluated = evaluated[evaluated["season"] == test_season].copy()
    stacker = evaluated[evaluated["variant"] == "market_correction_stacker"].copy()
    override = draw_override_predictions(stacker, raw)
    override = override[override["season"] == test_season]
    evaluated = pd.concat([evaluated, override], ignore_index=True, sort=False)

    prediction_report = {
        variant: prediction_metrics(part)
        for variant, part in evaluated.groupby("variant", sort=True)
    }
    betting_report = {}
    for variant in sorted(evaluated["variant"].unique()):
        if variant in {"market_only", "draw_specialist_override"}:
            continue
        bets = select_portfolio_bets(evaluated, strategy_to_model, variant)
        betting_report[variant] = betting_metrics(bets)

    retuned_filter_report = {}
    retunable_variants = [
        variant
        for variant in raw["variant"].unique()
        if variant
        in {
            "current",
            "unweighted",
            "soft_class_weight",
            "recency_decay_0_80",
            "rolling_5_seasons",
            "alternate_scope",
            "research_seed_7066",
            "seed_ensemble_5",
        }
    ]
    for variant in sorted(retunable_variants):
        retuned_filter_report[variant] = tune_filters_on_validation(
            raw,
            strategy_to_model,
            variant,
            validation_season=validation_season,
            test_season=test_season,
        )

    return {
        "protocol": {
            "training_max_season": validation_season - 1,
            "validation_season": validation_season,
            "untouched_test_season": test_season,
            "note": "The same fitted base model scores validation and test; no 2025 result is used for fitting or calibration.",
        },
        "prediction_results": prediction_report,
        "betting_results_same_final_four_rules": betting_report,
        "betting_results_filters_retuned_on_validation": retuned_filter_report,
        "expected_current_reference": {
            "bets": 101,
            "profit_units": 7.08,
            "roi": 0.07009900990099,
        },
        "training_audit": audit_rows,
    }


def main() -> None:
    args = parse_args()
    dataset = pd.read_csv(args.dataset)
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["season"] = pd.to_numeric(dataset["season"], errors="coerce")
    dataset = dataset[dataset["target"].notna() & dataset["season"].notna()].copy()
    dataset["target"] = dataset["target"].astype(int)

    configurations, strategy_to_model = model_configurations()
    output = Path(args.output)
    if args.latest_holdout_only:
        holdout = latest_holdout_report(dataset, configurations, strategy_to_model)
        report = {}
        if output.exists():
            report = json.loads(output.read_text(encoding="utf-8"))
        report["latest_untouched_holdout"] = holdout
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report={output}", flush=True)
        return

    prediction_frames = []
    training_audit = []
    calibration_season = args.first_test_season - 1
    for season in range(calibration_season, args.last_test_season + 1):
        for model_id, strategy in configurations:
            for variant in VARIANTS:
                frame, audit = fit_predict_variant(dataset, strategy, season, variant)
                if frame.empty:
                    continue
                frame["model_id"] = model_id
                prediction_frames.append(frame)
                training_audit.append(
                    {
                        "season": season,
                        "model_id": model_id,
                        "variant": variant,
                        **audit,
                    }
                )
            print(f"finished season={season} model={model_id}", flush=True)

    raw = pd.concat(prediction_frames, ignore_index=True)
    postprocessed = build_postprocessed_predictions(raw, args.first_test_season)
    market = market_predictions(raw, args.first_test_season)
    all_predictions = pd.concat([raw, postprocessed, market], ignore_index=True, sort=False)
    stacker = all_predictions[all_predictions["variant"] == "market_correction_stacker"].copy()
    override = draw_override_predictions(stacker, raw)
    all_predictions = pd.concat([all_predictions, override], ignore_index=True, sort=False)
    evaluated = all_predictions[
        (all_predictions["season"] >= args.first_test_season)
        & (all_predictions["season"] <= args.last_test_season)
    ].copy()

    prediction_report = {}
    for variant, part in evaluated.groupby("variant", sort=True):
        prediction_report[variant] = {
            "overall": prediction_metrics(part),
            "by_season": {
                str(int(season)): prediction_metrics(season_rows)
                for season, season_rows in part.groupby("season", sort=True)
            },
            "by_league": {
                league: prediction_metrics(league_rows)
                for league, league_rows in part.groupby("league", sort=True)
            },
        }

    betting_report = {}
    betting_variants = [
        variant
        for variant in evaluated["variant"].unique()
        if variant not in {"market_only", "draw_specialist_override"}
    ]
    for variant in sorted(betting_variants):
        bets = select_portfolio_bets(evaluated, strategy_to_model, variant)
        betting_report[variant] = {
            "full_period": betting_metrics(bets),
            "scientific_report_period_2022_2025": betting_metrics(
                bets[bets["season"] >= 2022] if not bets.empty else bets
            ),
        }

    report = {
        "method": {
            "name": "rolling_origin_challenger_tournament",
            "first_test_season": args.first_test_season,
            "last_test_season": args.last_test_season,
            "calibration": "Each test season uses only the immediately preceding season to fit post-processing.",
            "training": "Every base model uses only seasons strictly earlier than its test season.",
            "production_changed": False,
        },
        "dataset": {
            "rows": int(len(dataset)),
            "min_season": int(dataset["season"].min()),
            "max_season": int(dataset["season"].max()),
            "available_live_feature_families": ["xG", "Elo", "form", "rest", "opening_market"],
            "unavailable_historical_feature_families": [
                "injuries",
                "suspensions",
                "confirmed_lineups",
                "promotion_flag",
            ],
        },
        "model_configurations": [
            {
                "model_id": model_id,
                "train_league": strategy.train_league or "ALL",
                "bet_league": strategy.bet_league,
                "n_estimators": strategy.n_estimators,
                "params": strategy.params,
            }
            for model_id, strategy in configurations
        ],
        "prediction_results": prediction_report,
        "betting_results_same_frozen_filters": betting_report,
        "training_audit": training_audit,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={output}", flush=True)


if __name__ == "__main__":
    main()
