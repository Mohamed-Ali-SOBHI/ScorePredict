from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import version as package_version
import json
import os
import pickle
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from data_pipeline.market_data import normalize_team_name
from data_pipeline.team_registry import read_registry
from inference.portfolio_presets import FROZEN_REFERENCE_TRAIN_MAX_SEASON, FrozenStrategy
from train.make_dataset import (
    EloConfig,
    WINDOWS_DEFAULT,
    add_draw_specialist_features,
    add_team_prematch_features,
    build_home_perspective_dataset,
    compute_match_elo,
    load_team_match_rows,
)
from train.ml_common import (
    DRAW_TARGET,
    build_draw_binary_xgb_model,
    build_xgb_model,
    get_feature_cols,
    make_draw_target,
    make_sample_weight,
)
from train.strategy_search_common import profile_filter_mask


DEFAULT_LIVE_TRAIN_MAX_SEASON = FROZEN_REFERENCE_TRAIN_MAX_SEASON
OUTCOME_TO_INDEX = {"away_win": 0, "draw": 1, "home_win": 2}
OUTCOME_TO_PROBA_COL = {
    "away_win": "pred_away_win",
    "draw": "pred_draw",
    "home_win": "pred_home_win",
}
OUTCOME_TO_MARKET_COL = {
    "away_win": "market_away_prob_open",
    "draw": "market_draw_prob_open",
    "home_win": "market_home_prob_open",
}
OUTCOME_TO_ODDS_COL = {
    "away_win": "market_away_win_odds_open",
    "draw": "market_draw_odds_open",
    "home_win": "market_home_win_odds_open",
}
MARKET_PROB_COLS_MODEL_ORDER = [
    "market_away_prob_open",
    "market_draw_prob_open",
    "market_home_prob_open",
]
MODEL_CACHE_FORMAT_VERSION = 2
SUPPORTED_TRAINING_WEIGHT_MODES = {
    "balanced",
    "unweighted",
    "recency_decay_0_80",
}


@dataclass(frozen=True)
class ModelBundle:
    model_variant: str
    train_league: str
    train_max_season: int
    feature_cols: list[str]
    model: object
    secondary_feature_cols: list[str] | None = None
    secondary_model: object | None = None


def _model_training_code_fingerprint() -> str:
    paths = [
        Path(__file__),
        REPO_ROOT / "inference" / "portfolio_presets.py",
        REPO_ROOT / "train" / "make_dataset.py",
        REPO_ROOT / "train" / "ml_common.py",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _model_runtime_signature() -> dict[str, str]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "numpy": package_version("numpy"),
        "pandas": package_version("pandas"),
        "scikit-learn": package_version("scikit-learn"),
        "xgboost": package_version("xgboost"),
    }


def _model_cache_fingerprint(
    dataset: pd.DataFrame,
    strategies: Sequence[FrozenStrategy],
    *,
    train_max_season: int,
) -> str:
    """Identify the exact frozen strategy, code and labelled rows used for fitting."""
    digest = hashlib.sha256()
    manifest = {
        "format_version": MODEL_CACHE_FORMAT_VERSION,
        "train_max_season": int(train_max_season),
        "strategies": [asdict(strategy) for strategy in strategies],
        "runtime": _model_runtime_signature(),
        "training_code": _model_training_code_fingerprint(),
    }
    digest.update(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    for strategy in sorted(strategies, key=lambda item: item.name):
        train_df = dataset[
            (dataset["season"] <= train_max_season) & dataset["target"].notna()
        ].copy()
        if strategy.train_league:
            train_df = train_df[train_df["league"] == strategy.train_league].copy()
        if train_df.empty:
            raise ValueError(
                f"No training rows available for train_league={strategy.train_league or 'ALL'}"
            )

        feature_cols = get_feature_cols(
            train_df,
            include_draw_features=(strategy.model_variant == "draw_binary"),
        )
        if strategy.model_variant == "draw_consensus":
            feature_cols += get_feature_cols(train_df, include_draw_features=True)
        fingerprint_cols = sorted(
            set(feature_cols + ["match_id", "league", "season", "target"])
        )
        stable = train_df[fingerprint_cols].sort_values(
            ["season", "league", "match_id"],
            kind="mergesort",
        )
        digest.update(strategy.name.encode("utf-8"))
        digest.update("\x1f".join(fingerprint_cols).encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(stable, index=False).values.tobytes())
    return digest.hexdigest()


def load_or_train_frozen_models(
    dataset: pd.DataFrame,
    strategies: Sequence[FrozenStrategy],
    *,
    train_max_season: int = DEFAULT_LIVE_TRAIN_MAX_SEASON,
    cache_path: str | Path | None = None,
    force_retrain: bool = False,
) -> tuple[dict[str, ModelBundle], str]:
    """Load a validated immutable model bundle, fitting only on a cache miss."""
    expected_fingerprint = _model_cache_fingerprint(
        dataset,
        strategies,
        train_max_season=train_max_season,
    )
    resolved_cache = Path(cache_path).resolve() if cache_path else None

    if resolved_cache is not None and resolved_cache.exists() and not force_retrain:
        try:
            with resolved_cache.open("rb") as handle:
                payload = pickle.load(handle)
            bundles = payload["bundles"]
            expected_names = {strategy.name for strategy in strategies}
            if payload.get("format_version") != MODEL_CACHE_FORMAT_VERSION:
                raise ValueError("unsupported model cache format")
            if payload.get("fingerprint") != expected_fingerprint:
                raise ValueError("model cache fingerprint does not match")
            if set(bundles) != expected_names:
                raise ValueError("model cache does not contain the expected strategies")
            return bundles, "cache"
        except Exception as exc:  # A broken cache must never block live predictions.
            print(f"Ignoring invalid frozen model cache {resolved_cache}: {exc}", file=sys.stderr)

    bundles = train_frozen_models(
        dataset,
        list(strategies),
        train_max_season=train_max_season,
    )
    if resolved_cache is not None:
        try:
            resolved_cache.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = resolved_cache.with_suffix(resolved_cache.suffix + ".tmp")
            payload = {
                "format_version": MODEL_CACHE_FORMAT_VERSION,
                "fingerprint": expected_fingerprint,
                "runtime": _model_runtime_signature(),
                "bundles": bundles,
            }
            with temporary_path.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(temporary_path, resolved_cache)
        except (OSError, pickle.PickleError) as exc:
            print(f"Unable to save frozen model cache {resolved_cache}: {exc}", file=sys.stderr)
    return bundles, "trained"


def infer_season_from_date(date_value: pd.Timestamp) -> int:
    return date_value.year if date_value.month >= 7 else date_value.year - 1


def load_historical_team_rows(data_dir: str) -> pd.DataFrame:
    return load_team_match_rows(data_dir)


def load_current_team_registry(data_dir: str) -> pd.DataFrame:
    records = read_registry(data_dir).get("teams", [])
    return pd.DataFrame(records, columns=["league", "season", "team_id", "team_name"])


def prepare_fixture_frame(fixtures: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date",
        "league",
        "home_team",
        "away_team",
        "home_win_odds_open",
        "draw_odds_open",
        "away_win_odds_open",
    }
    missing = required.difference(fixtures.columns)
    if missing:
        raise ValueError(f"fixtures dataframe is missing columns: {sorted(missing)}")

    result = fixtures.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["season"] = result["date"].map(infer_season_from_date).astype(int)
    result["home_team_norm"] = result["home_team"].map(normalize_team_name)
    result["away_team_norm"] = result["away_team"].map(normalize_team_name)
    return result.sort_values(["date", "league", "home_team_norm", "away_team_norm"]).reset_index(drop=True)


def build_team_lookup(
    team_rows: pd.DataFrame,
    registry_rows: pd.DataFrame | None = None,
) -> dict[tuple[str, str], dict[str, str]]:
    rows = team_rows.copy()
    rows["team_name_norm"] = rows["team_name"].map(normalize_team_name)
    latest = (
        rows.sort_values(["season", "date"])
        .groupby(["league", "team_name_norm"], as_index=False)
        .tail(1)
        .copy()
    )

    lookup: dict[tuple[str, str], dict[str, str]] = {}
    for row in latest.itertuples(index=False):
        lookup[(row.league, row.team_name_norm)] = {
            "team_id": str(row.team_id),
            "team_name": row.team_name,
        }

    if registry_rows is not None and not registry_rows.empty:
        registry = registry_rows.copy()
        registry["team_name_norm"] = registry["team_name"].map(normalize_team_name)
        registry = registry.sort_values(["season", "league", "team_name_norm"])
        registry = registry.groupby(["league", "team_name_norm"], as_index=False).tail(1)
        for row in registry.itertuples(index=False):
            lookup[(row.league, row.team_name_norm)] = {
                "team_id": str(row.team_id),
                "team_name": row.team_name,
            }
    return lookup


def append_future_fixtures(
    team_rows: pd.DataFrame,
    fixtures: pd.DataFrame,
    registry_rows: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    if fixtures.empty:
        return team_rows.copy(), []

    lookup = build_team_lookup(team_rows, registry_rows)
    latest_seen_date_by_league = (
        team_rows.groupby("league", sort=False)["date"].max().to_dict()
    )

    synthetic_rows = []
    future_match_ids: list[str] = []

    for idx, fixture in enumerate(fixtures.itertuples(index=False), start=1):
        home_info = lookup.get((fixture.league, fixture.home_team_norm))
        away_info = lookup.get((fixture.league, fixture.away_team_norm))
        if home_info is None or away_info is None:
            missing = fixture.home_team_norm if home_info is None else fixture.away_team_norm
            raise ValueError(
                f"Unable to map future fixture team to Understat team_id for league {fixture.league}: {missing!r}"
            )

        match_date = pd.Timestamp(fixture.date)
        latest_seen = latest_seen_date_by_league.get(fixture.league)
        if pd.notna(latest_seen) and match_date <= latest_seen:
            match_date = latest_seen + pd.Timedelta(minutes=idx)

        home_id = home_info["team_id"]
        away_id = away_info["team_id"]
        sorted_ids = sorted([home_id, away_id])
        match_id = f"{fixture.league} {fixture.season}_{sorted_ids[0]}_{sorted_ids[1]}_{match_date.isoformat()}"
        future_match_ids.append(match_id)

        synthetic_rows.extend(
            [
                {
                    "match_id": match_id,
                    "date": match_date,
                    "is_home": True,
                    "team_id": home_id,
                    "team_name": home_info["team_name"],
                    "result": np.nan,
                    "opponent_id": away_id,
                    "opponent_name": away_info["team_name"],
                    "team_xG": np.nan,
                    "opponent_xG": np.nan,
                    "team_deep": np.nan,
                    "opponent_deep": np.nan,
                    "team_ppda_att": np.nan,
                    "team_ppda_def": np.nan,
                    "team_win_odds_open": fixture.home_win_odds_open,
                    "draw_odds_open": fixture.draw_odds_open,
                    "opponent_win_odds_open": fixture.away_win_odds_open,
                    "season_key": f"{fixture.league} {fixture.season}",
                    "league": fixture.league,
                    "season": fixture.season,
                },
                {
                    "match_id": match_id,
                    "date": match_date,
                    "is_home": False,
                    "team_id": away_id,
                    "team_name": away_info["team_name"],
                    "result": np.nan,
                    "opponent_id": home_id,
                    "opponent_name": home_info["team_name"],
                    "team_xG": np.nan,
                    "opponent_xG": np.nan,
                    "team_deep": np.nan,
                    "opponent_deep": np.nan,
                    "team_ppda_att": np.nan,
                    "team_ppda_def": np.nan,
                    "team_win_odds_open": fixture.away_win_odds_open,
                    "draw_odds_open": fixture.draw_odds_open,
                    "opponent_win_odds_open": fixture.home_win_odds_open,
                    "season_key": f"{fixture.league} {fixture.season}",
                    "league": fixture.league,
                    "season": fixture.season,
                },
            ]
        )

    future_rows = pd.DataFrame(synthetic_rows)
    combined = pd.concat([team_rows, future_rows], ignore_index=True, sort=False)
    combined["date"] = pd.to_datetime(combined["date"])
    return combined, future_match_ids


def add_elo_features(matches: pd.DataFrame) -> pd.DataFrame:
    elo_input = matches[
        ["match_id", "league", "season", "date", "team_id", "opponent_id", "result"]
    ].rename(columns={"team_id": "home_team_id", "opponent_id": "away_team_id"})
    elo = compute_match_elo(
        elo_input,
        EloConfig(k=20.0, home_adv=60.0, season_carry=0.75),
    )
    return matches.merge(elo, on="match_id", how="left", validate="one_to_one")


def build_dataset_with_fixtures(
    team_rows: pd.DataFrame,
    fixtures: pd.DataFrame,
    registry_rows: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    combined_rows, future_match_ids = append_future_fixtures(team_rows, fixtures, registry_rows)
    combined_rows = add_team_prematch_features(combined_rows, windows=WINDOWS_DEFAULT)
    dataset = build_home_perspective_dataset(combined_rows, windows=WINDOWS_DEFAULT)
    dataset = add_elo_features(dataset)
    dataset = add_draw_specialist_features(dataset, windows=WINDOWS_DEFAULT)
    return dataset, future_match_ids


def make_strategy_sample_weight(
    train_df: pd.DataFrame,
    y_train: pd.Series,
    strategy: FrozenStrategy,
    *,
    train_max_season: int,
) -> pd.Series | None:
    mode = strategy.training_weight_mode
    if mode not in SUPPORTED_TRAINING_WEIGHT_MODES:
        raise ValueError(f"Unsupported training_weight_mode: {mode}")
    if mode == "unweighted":
        return None

    weights = make_sample_weight(y_train).astype(float)
    if mode == "recency_decay_0_80":
        ages = (train_max_season - pd.to_numeric(train_df["season"], errors="raise")).clip(
            lower=0
        )
        weights = weights * np.power(0.80, ages.to_numpy(dtype=float))
    return weights / float(weights.mean())


def train_frozen_models(
    dataset: pd.DataFrame,
    strategies: list[FrozenStrategy],
    *,
    train_max_season: int = DEFAULT_LIVE_TRAIN_MAX_SEASON,
) -> dict[str, ModelBundle]:
    bundles: dict[str, ModelBundle] = {}
    for strategy in strategies:
        train_league = strategy.train_league
        train_df = dataset[(dataset["season"] <= train_max_season) & dataset["target"].notna()].copy()
        if train_league:
            train_df = train_df[train_df["league"] == train_league].copy()
        if train_df.empty:
            raise ValueError(f"No training rows available for train_league={train_league or 'ALL'}")

        feature_cols = get_feature_cols(
            train_df,
            include_draw_features=(strategy.model_variant == "draw_binary"),
        )
        if strategy.model_variant == "draw_binary":
            if strategy.outcome != "draw":
                raise ValueError("draw_binary strategies are only supported for draw outcome")
            model = build_draw_binary_xgb_model(seed=42, n_estimators=strategy.n_estimators, **strategy.params)
            y_train = make_draw_target(train_df["target"])
            secondary_feature_cols = None
            secondary_model = None
        elif strategy.model_variant == "draw_consensus":
            if strategy.outcome != "draw":
                raise ValueError("draw_consensus strategies are only supported for draw outcome")
            feature_cols = get_feature_cols(train_df, include_draw_features=False)
            secondary_feature_cols = get_feature_cols(train_df, include_draw_features=True)
            model = build_xgb_model(seed=42, n_estimators=strategy.n_estimators, **strategy.params)
            y_train = train_df["target"].astype(int)
            secondary_model = build_draw_binary_xgb_model(
                seed=42,
                n_estimators=strategy.n_estimators,
                **strategy.params,
            )
            y_draw = make_draw_target(train_df["target"])
            secondary_model.fit(
                train_df[secondary_feature_cols],
                y_draw,
                sample_weight=make_strategy_sample_weight(
                    train_df,
                    y_draw,
                    strategy,
                    train_max_season=train_max_season,
                ),
            )
        else:
            model = build_xgb_model(seed=42, n_estimators=strategy.n_estimators, **strategy.params)
            y_train = train_df["target"].astype(int)
            secondary_feature_cols = None
            secondary_model = None
        model.fit(
            train_df[feature_cols],
            y_train,
            sample_weight=make_strategy_sample_weight(
                train_df,
                y_train,
                strategy,
                train_max_season=train_max_season,
            ),
        )
        bundles[strategy.name] = ModelBundle(
            model_variant=strategy.model_variant,
            train_league=train_league,
            train_max_season=train_max_season,
            feature_cols=feature_cols,
            model=model,
            secondary_feature_cols=secondary_feature_cols,
            secondary_model=secondary_model,
        )
    return bundles


def add_probability_columns(scored: pd.DataFrame, proba: np.ndarray) -> pd.DataFrame:
    result = scored.copy()
    result["pred_home_win"] = proba[:, 2]
    result["pred_draw"] = proba[:, 1]
    result["pred_away_win"] = proba[:, 0]
    return result


def add_draw_binary_probability_columns(scored: pd.DataFrame, draw_proba: np.ndarray) -> pd.DataFrame:
    result = scored.copy()
    result["pred_home_win"] = np.nan
    result["pred_draw"] = draw_proba
    result["pred_away_win"] = np.nan
    return result


def score_strategy_rows(
    future_df: pd.DataFrame,
    bundles: dict[str, ModelBundle],
    strategies: list[FrozenStrategy],
) -> pd.DataFrame:
    scored_frames = []
    for strategy in strategies:
        bundle = bundles[strategy.name]
        league_df = future_df[future_df["league"] == strategy.bet_league].copy()
        if league_df.empty:
            continue

        if bundle.model_variant == "draw_binary":
            draw_proba = bundle.model.predict_proba(league_df[bundle.feature_cols])[:, 1]
            league_df = add_draw_binary_probability_columns(league_df, draw_proba)
        elif bundle.model_variant == "draw_consensus":
            if bundle.secondary_model is None or bundle.secondary_feature_cols is None:
                raise ValueError(f"Missing secondary draw model for strategy {strategy.name}")
            multiclass_proba = bundle.model.predict_proba(league_df[bundle.feature_cols])
            binary_draw_proba = bundle.secondary_model.predict_proba(
                league_df[bundle.secondary_feature_cols]
            )[:, 1]
            league_df = add_probability_columns(league_df, multiclass_proba)
            league_df["multiclass_draw_probability"] = multiclass_proba[:, 1]
            league_df["binary_draw_probability"] = binary_draw_proba
            league_df["pred_draw"] = np.minimum(multiclass_proba[:, 1], binary_draw_proba)
        else:
            proba = bundle.model.predict_proba(league_df[bundle.feature_cols])
            league_df = add_probability_columns(league_df, proba)

        outcome = strategy.outcome
        market_col = OUTCOME_TO_MARKET_COL[outcome]
        odds_col = OUTCOME_TO_ODDS_COL[outcome]
        proba_col = OUTCOME_TO_PROBA_COL[outcome]

        league_df["strategy_name"] = strategy.name
        league_df["train_league"] = strategy.train_league or "ALL"
        league_df["bet_league"] = strategy.bet_league
        league_df["profile_filter"] = strategy.profile_filter
        league_df["selected_outcome"] = outcome
        league_df["selected_odds"] = league_df[odds_col]
        league_df["predicted_probability"] = league_df[proba_col]
        league_df["market_probability"] = league_df[market_col]
        league_df["edge"] = league_df["predicted_probability"] - league_df["market_probability"]
        league_df["expected_value"] = league_df["predicted_probability"] * league_df["selected_odds"] - 1.0
        league_df["raw_model_probability"] = league_df["predicted_probability"]
        league_df["value_score"] = league_df["edge"]
        league_df["raw_expected_value"] = league_df["expected_value"]
        league_df["probability_note"] = (
            "min_multiclass_draw_and_binary_draw_raw_probability"
            if bundle.model_variant == "draw_consensus"
            else "raw_xgb_probability_not_calibrated"
        )
        league_df["train_max_season"] = bundle.train_max_season

        market_probs = league_df[MARKET_PROB_COLS_MODEL_ORDER].to_numpy()
        favorite_idx = market_probs.argmax(axis=1)
        if bundle.model_variant == "draw_binary":
            league_df["bet_is_market_favorite"] = favorite_idx == DRAW_TARGET
        else:
            league_df["bet_is_market_favorite"] = favorite_idx == OUTCOME_TO_INDEX[outcome]

        selected_mask = (
            (league_df["expected_value"] > strategy.threshold)
            & (league_df["edge"] >= strategy.edge_min)
            & (league_df["selected_odds"] >= strategy.odds_min)
            & (league_df["selected_odds"] < strategy.odds_max)
        )
        if strategy.market_favorite_mode == "favorite":
            selected_mask &= league_df["bet_is_market_favorite"]
        elif strategy.market_favorite_mode == "nonfavorite":
            selected_mask &= ~league_df["bet_is_market_favorite"]
        selected_mask &= profile_filter_mask(league_df, strategy.profile_filter)

        league_df["recommended_bet"] = np.where(selected_mask, outcome, "")
        league_df["bet_key"] = league_df["match_id"].astype(str) + "|" + league_df["selected_outcome"].astype(str)
        scored_frames.append(league_df)

    if not scored_frames:
        return pd.DataFrame()
    return pd.concat(scored_frames, ignore_index=True).sort_values(["date", "league", "team_name", "strategy_name"])


def dedupe_recommended_bets(strategy_rows: pd.DataFrame) -> pd.DataFrame:
    recommendations = strategy_rows[strategy_rows["recommended_bet"] != ""].copy()
    if recommendations.empty:
        return recommendations

    strategy_names = (
        recommendations.groupby("bet_key", sort=False)["strategy_name"]
        .agg(lambda values: "|".join(dict.fromkeys(values)))
        .rename("strategy_names")
    )
    deduped = (
        recommendations.sort_values(["bet_key", "expected_value", "edge"], ascending=[True, False, False])
        .drop_duplicates(subset=["bet_key"], keep="first")
        .copy()
    )
    deduped = deduped.merge(strategy_names, on="bet_key", how="left", validate="one_to_one")
    return deduped


def assign_flat_stakes(
    recommendations: pd.DataFrame,
    *,
    bankroll_eur: float,
    stake_fraction: float,
    max_total_exposure_fraction: float,
) -> pd.DataFrame:
    bets = recommendations.copy()
    if bets.empty:
        bets["stake_eur"] = pd.Series(dtype="float64")
        bets["max_total_exposure_eur"] = pd.Series(dtype="float64")
        bets["potential_profit_eur_if_win"] = pd.Series(dtype="float64")
        return bets

    flat_stake = bankroll_eur * stake_fraction
    max_total = bankroll_eur * max_total_exposure_fraction
    stake = flat_stake if len(bets) * flat_stake <= max_total else max_total / len(bets)

    bets["stake_eur"] = round(stake, 2)
    bets["max_total_exposure_eur"] = round(min(len(bets) * stake, max_total), 2)
    bets["potential_profit_eur_if_win"] = ((bets["selected_odds"] - 1.0) * bets["stake_eur"]).round(2)
    return bets
