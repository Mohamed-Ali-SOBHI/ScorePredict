"""Reproducible research tournament; no production imports with side effects/writes.

Each fold trains through T-2, selects betting filters on T-1, and scores T.
Candidate selection uses 2019-2023 only, before computing confirmation 2024-2025.
All these seasons have been explored previously: confirmation is retrospective,
not a new untouched holdout or prospective evidence.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import softmax
import sklearn
from threadpoolctl import threadpool_info, threadpool_limits
import xgboost

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.portfolio_presets import PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
from train.evaluate_model_challengers import (
    MARKET_PROBABILITY_COLUMNS,
    maximum_drawdown,
    normalized_probabilities,
    prediction_metrics,
)
from train.ml_common import build_draw_binary_xgb_model, build_xgb_model, get_feature_cols, make_sample_weight

PROBS = ["p_away", "p_draw", "p_home"]
LEAGUES = ("Bundesliga", "EPL", "Serie_A")
ALL_LEAGUES = (*LEAGUES, "La_liga", "Ligue_1")
BASELINE = "unweighted__legacy"
POLICIES = ("legacy", "pooled_cautious", "fixed_ev_5pct")
SOURCE_FILES = (
    "train/research_challengers_v2.py", "train/evaluate_model_challengers.py",
    "train/ml_common.py", "inference/portfolio_presets.py",
)


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str = "xgb"
    scope: str = "global"
    class_balanced: bool = False
    decay: float = 1.0
    depth: int = 2
    trees: int = 200
    prior: bool = False
    enriched: bool = False
    seeds: tuple[int, ...] = (42,)
    penalty: float = 0.05


CANDIDATES = (
    Candidate("current", family="legacy", class_balanced=True),
    Candidate("unweighted", family="legacy"),
    Candidate("recency", family="legacy", class_balanced=True, decay=0.8),
    Candidate("unweighted_ensemble", family="legacy", seeds=(42, 73, 2026)),
    Candidate("shallow_local", scope="local"),
    Candidate("shallow_global", depth=3),
    Candidate("shallow_recent", depth=3, decay=0.85),
    Candidate("market_residual", prior=True),
    Candidate("market_residual_recent", prior=True, decay=0.85),
    Candidate("market_residual_enriched", prior=True, enriched=True),
    Candidate("linear_market_residual", family="linear", enriched=True, penalty=0.05),
    Candidate("linear_market_residual_strong", family="linear", enriched=True, penalty=0.2),
    Candidate("market_only", family="market"),
)
ENSEMBLES = {
    "diverse_ensemble": ("unweighted_ensemble", "shallow_global", "market_residual"),
    "market_consensus": ("market_residual", "linear_market_residual", "market_only"),
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def temporal_split(dataset: pd.DataFrame, season: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = dataset[dataset.season < season - 1].copy()
    validation = dataset[dataset.season == season - 1].copy()
    test = dataset[dataset.season == season].copy()
    if train.empty or validation.empty or test.empty:
        raise ValueError(f"Incomplete temporal fold {season}")
    if not train.date.max() < validation.date.min() or not validation.date.max() < test.date.min():
        raise ValueError(f"Overlapping calendar dates in fold {season}")
    for left, right in ((train, validation), (train, test), (validation, test)):
        if set(left.match_id) & set(right.match_id):
            raise ValueError("A match occurs in more than one temporal partition")
    return train, validation, test


def features(frame: pd.DataFrame, enriched: bool) -> pd.DataFrame:
    cols = get_feature_cols(frame, include_draw_features=True)
    if enriched:
        # All these fields are shifted/expanding pre-match inputs in make_dataset.
        # Explicit whitelist excludes result, goals, identifiers and closing odds.
        for prefix in ("team_", "opponent_"):
            cols += [f"{prefix}xG_last_{w}_carry" for w in (1, 3, 5)]
            cols += [f"{prefix}xG_against_last_{w}_carry" for w in (1, 3, 5)]
            cols += [f"{prefix}rest_days", f"{prefix}matches_played_in_season_before"]
        cols += ["team_season_avg_xG_carry", "opponent_season_avg_xG_carry"]
    result = frame[list(dict.fromkeys(c for c in cols if c in frame))].copy()
    for league in ALL_LEAGUES:
        result[f"league_{league}"] = (frame.league == league).astype(float)
    return result.replace([np.inf, -np.inf], np.nan).astype(float)


def weights(rows: pd.DataFrame, target: pd.Series, candidate: Candidate) -> np.ndarray | None:
    if not candidate.class_balanced and candidate.decay == 1:
        return None
    weight = make_sample_weight(target).to_numpy() if candidate.class_balanced else np.ones(len(rows))
    weight *= candidate.decay ** (int(rows.season.max()) - rows.season.to_numpy())
    return weight / weight.mean()


def market(frame: pd.DataFrame) -> np.ndarray:
    return normalized_probabilities(frame[list(MARKET_PROBABILITY_COLUMNS)].to_numpy())


def fit_linear_residual(train: pd.DataFrame, score: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    x_train, x_score = features(train, candidate.enriched), features(score, candidate.enriched)
    median = x_train.median().fillna(0)
    x_train = x_train.fillna(median)
    mean, scale = x_train.mean(), x_train.std().replace(0, 1).fillna(1)
    x = np.column_stack([np.ones(len(train)), ((x_train - mean) / scale).clip(-8, 8)])
    z = np.column_stack([np.ones(len(score)), ((x_score.fillna(median) - mean) / scale).clip(-8, 8)])
    offsets = np.log(market(train))
    targets = np.eye(3)[train.target.to_numpy(dtype=int)]
    penalty = np.ones((x.shape[1], 3)) * candidate.penalty
    penalty[0] = 0.002

    def objective(flat):
        coefficients = flat.reshape(x.shape[1], 3)
        probs = softmax(offsets + x @ coefficients, axis=1)
        loss = -np.sum(targets * np.log(np.clip(probs, 1e-12, 1))) / len(train)
        loss += 0.5 * np.sum(penalty * coefficients ** 2)
        gradient = x.T @ (probs - targets) / len(train) + penalty * coefficients
        return float(loss), gradient.ravel()

    solution = minimize(objective, np.zeros(x.shape[1] * 3), jac=True, method="L-BFGS-B",
                        options={"maxiter": 400, "ftol": 1e-10})
    if not solution.success:
        raise RuntimeError(f"Linear residual optimizer failed: {solution.message}")
    return softmax(np.log(market(score)) + z @ solution.x.reshape(x.shape[1], 3), axis=1)


def train_candidate(train: pd.DataFrame, score: pd.DataFrame, candidate: Candidate, threads: int = 2) -> tuple[pd.DataFrame, list[dict]]:
    score = score[score.league.isin(LEAGUES)].copy()
    metadata = ["match_id", "date", "season", "league", "target", "team_name", "opponent_name",
                "market_away_win_odds_open", "market_draw_odds_open", "market_home_win_odds_open",
                *MARKET_PROBABILITY_COLUMNS]
    result = score[metadata].copy()
    audits = []
    if candidate.family == "market":
        result[PROBS] = market(score)
        result["p_binary_draw"] = result.p_draw
        return result.sort_values("match_id").reset_index(drop=True), audits
    if candidate.family == "linear":
        result[PROBS] = fit_linear_residual(train, score, candidate)
        result["p_binary_draw"] = result.p_draw
        audits.append({"scope": "ALL", "train_rows": len(train), "train_max_season": int(train.season.max())})
        return result.sort_values("match_id").reset_index(drop=True), audits

    groups = LEAGUES if candidate.family == "legacy" or candidate.scope == "local" else ("ALL",)
    for league in groups:
        scope = league
        if candidate.family == "legacy":
            strategy = next(s for s in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026 if s.bet_league == league)
            scope = strategy.train_league or "ALL"
            params = {**strategy.params, "n_estimators": strategy.n_estimators}
        else:
            params = dict(n_estimators=candidate.trees, max_depth=candidate.depth, learning_rate=0.03,
                          min_child_weight=40, subsample=0.85, colsample_bytree=0.85, reg_lambda=30.0, gamma=0.25)
        fit_rows = train if scope == "ALL" else train[train.league == scope]
        score_rows = score if league == "ALL" else score[score.league == league]
        if candidate.family == "legacy":
            multi_cols = get_feature_cols(train)
            binary_cols = get_feature_cols(train, include_draw_features=True)
            x_train, x_test = fit_rows[multi_cols], score_rows[multi_cols]
            b_train, b_test = fit_rows[binary_cols], score_rows[binary_cols]
        else:
            x_train, x_test = features(fit_rows, candidate.enriched), features(score_rows, candidate.enriched)
            b_train, b_test = x_train, x_test
        y = fit_rows.target.astype(int)
        binary_y = (y == 1).astype(int)
        multi_fit_args, multi_test_args, binary_fit_args, binary_test_args = {}, {}, {}, {}
        if candidate.prior:
            p_train, p_test = market(fit_rows), market(score_rows)
            multi_fit_args["base_margin"] = np.log(p_train)
            multi_test_args["base_margin"] = np.log(p_test)
            binary_fit_args["base_margin"] = np.log(p_train[:, 1] / (1 - p_train[:, 1]))
            binary_test_args["base_margin"] = np.log(p_test[:, 1] / (1 - p_test[:, 1]))
        multiclass_predictions, binary_predictions = [], []
        for seed in candidate.seeds:
            model = build_xgb_model(seed=seed, **params).set_params(n_jobs=threads)
            model.fit(x_train, y, sample_weight=weights(fit_rows, y, candidate), **multi_fit_args)
            multiclass_predictions.append(model.predict_proba(x_test, **multi_test_args))
            binary = build_draw_binary_xgb_model(seed=seed, **params).set_params(n_jobs=threads)
            binary.fit(b_train, binary_y, sample_weight=weights(fit_rows, binary_y, candidate), **binary_fit_args)
            binary_predictions.append(binary.predict_proba(b_test, **binary_test_args)[:, 1])
        result.loc[score_rows.index, PROBS] = np.mean(multiclass_predictions, axis=0)
        result.loc[score_rows.index, "p_binary_draw"] = np.mean(binary_predictions, axis=0)
        audits.append({"scope": scope, "score_league": league, "train_rows": len(fit_rows),
                       "train_max_season": int(fit_rows.season.max()), "features": list(x_train.columns),
                       "binary_features": list(b_train.columns), "seeds": list(candidate.seeds)})
    return result.sort_values("match_id").reset_index(drop=True), audits


def draw_scores(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["selected_odds"] = result.market_draw_odds_open.astype(float)
    result["draw_signal"] = np.minimum(result.p_draw, result.p_binary_draw)
    result["expected_value"] = result.draw_signal * result.selected_odds - 1
    result["edge"] = result.draw_signal - result.market_draw_prob_open
    result["nonfavorite"] = market(result).argmax(axis=1) != 1
    return result


def rule_mask(frame: pd.DataFrame, strategy) -> np.ndarray:
    return ((frame.league == strategy.bet_league) & frame.nonfavorite
            & (frame.selected_odds >= strategy.odds_min) & (frame.selected_odds < strategy.odds_max)).to_numpy()


def fit_betting_policy(validation: pd.DataFrame, policy: str) -> list[dict]:
    """Only this function sees validation outcomes; test labels are never accepted."""
    validation = draw_scores(validation)
    strategies = PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
    if policy == "fixed_ev_5pct":
        return [{"strategy": s.name, "threshold": 0.05, "edge_min": 0.0} for s in strategies]
    if policy == "production_fixed":
        return [{"strategy": s.name, "threshold": s.threshold, "edge_min": s.edge_min} for s in strategies]
    if policy not in {"legacy", "pooled_cautious"}:
        raise ValueError(f"Unknown policy: {policy}")
    masks = [rule_mask(validation, s) for s in strategies]
    if policy == "pooled_cautious":
        masks = [np.logical_or.reduce(masks)]
    decisions = []
    # Match the original grid exactly, including > for EV and >= for edge.
    thresholds = np.arange(0.05, 0.551, 0.05)
    edges = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)
    for index, static in enumerate(masks):
        best = None
        for threshold in thresholds:
            for edge in edges:
                subset = validation.loc[static & (validation.expected_value.to_numpy() > threshold)
                                        & (validation.edge.to_numpy() >= edge)]
                minimum = 20 if policy == "legacy" else 60
                if len(subset) < minimum:
                    continue
                profit = np.where(subset.target.to_numpy() == 1, subset.selected_odds.to_numpy() - 1, -1)
                roi = float(profit.mean())
                if roi < 0.02:
                    continue
                score = roi if policy == "legacy" else roi - float(profit.std(ddof=1) / np.sqrt(len(profit)))
                if policy == "pooled_cautious" and score <= 0:
                    continue
                rank = (score, float(profit.sum()), len(subset))
                if best is None or rank > best[0]:
                    best = (rank, {"threshold": float(threshold), "edge_min": edge,
                                   "validation_bets": len(subset), "validation_roi": roi})
        if best is not None:
            selected_strategies = strategies if policy == "pooled_cautious" else [strategies[index]]
            decisions.extend({"strategy": s.name, **best[1]} for s in selected_strategies)
    return decisions


def apply_betting_policy(test: pd.DataFrame, decisions: list[dict]) -> pd.DataFrame:
    test = draw_scores(test)
    chosen = np.zeros(len(test), dtype=bool)
    strategy_map = {s.name: s for s in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026}
    for decision in decisions:
        chosen |= (rule_mask(test, strategy_map[decision["strategy"]])
                   & (test.expected_value.to_numpy() > decision["threshold"])
                   & (test.edge.to_numpy() >= decision["edge_min"]))
    return test.loc[chosen].copy()


def summarize_bets(bets: pd.DataFrame, *, bootstrap: bool = True) -> dict:
    if bets.empty:
        return {"bets": 0, "profit_units": 0.0, "roi": None, "hit_rate": None,
                "max_drawdown_units": 0.0, "positive_seasons": 0, "by_season": {}}
    ordered = bets.sort_values(["date", "match_id"])
    if ordered.match_id.duplicated().any():
        raise ValueError("A fixture was counted twice in one portfolio")
    profit = np.where(ordered.target.to_numpy() == 1, ordered.selected_odds.to_numpy() - 1, -1)
    ordered = ordered.assign(profit=profit)
    by_season = {str(int(year)): {"bets": len(rows), "roi": float(rows.profit.mean()),
                                "profit_units": float(rows.profit.sum())}
                 for year, rows in ordered.groupby("season")}
    value = {"bets": len(ordered), "profit_units": float(profit.sum()), "roi": float(profit.mean()),
             "hit_rate": float((ordered.target == 1).mean()), "average_odds": float(ordered.selected_odds.mean()),
             "max_drawdown_units": maximum_drawdown(profit), "by_season": by_season,
             "positive_seasons": sum(x["profit_units"] > 0 for x in by_season.values()),
             "roi_with_5pct_shorter_odds": float(np.where(ordered.target == 1, ordered.selected_odds * .95 - 1, -1).mean())}
    if bootstrap:
        # Resample whole calendar dates to keep correlated same-day bets together.
        blocks = ordered.groupby(ordered.date.dt.normalize()).profit.agg(["sum", "count"])
        rng = np.random.default_rng(20260905)
        indexes = rng.integers(0, len(blocks), size=(3000, len(blocks)))
        returns = blocks["sum"].to_numpy()[indexes].sum(axis=1) / blocks["count"].to_numpy()[indexes].sum(axis=1)
        value["day_block_roi_interval_95pct"] = [float(x) for x in np.quantile(returns, [.025, .975])]
        # Descriptive interval; not adjusted for the search across candidates.
    return value


def choose_candidate(bet_frames: dict[str, pd.DataFrame], through: int = 2023) -> tuple[str | None, list[dict]]:
    leaderboard = []
    for name, bets in bet_frames.items():
        development = bets[bets.season <= through]
        summary = summarize_bets(development)
        eligible = (summary["bets"] >= 150 and summary["positive_seasons"] >= 3
                    and summary["roi"] > 0)
        bound = summary.get("day_block_roi_interval_95pct", [-1])[0]
        leaderboard.append({"name": name, "eligible": eligible, "selection_score": bound,
                            "development": summary})
    leaderboard.sort(key=lambda r: (r["eligible"], r["selection_score"], r["development"]["bets"]), reverse=True)
    winner = next((row["name"] for row in leaderboard if row["eligible"] and not row["name"].startswith("market_only")), None)
    return winner, leaderboard


def run_fold(dataset: pd.DataFrame, season: int, output: Path, manifest_id: str, threads: int = 2) -> tuple[dict, dict, dict]:
    train, validation, test = temporal_split(dataset, season)
    score = pd.concat([validation, test], ignore_index=False)
    frames, audits, bets, decisions = {}, {}, {}, {}
    cache_dir = output / "prediction_cache" / manifest_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    for candidate in CANDIDATES:
        cache_path = cache_dir / f"{season}_{candidate.name}.csv.gz"
        audit_path = cache_dir / f"{season}_{candidate.name}.json"
        started = time.monotonic()
        if cache_path.exists() and audit_path.exists():
            frame = pd.read_csv(cache_path, parse_dates=["date"])
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        else:
            frame, audit = train_candidate(train, score, candidate, threads=threads)
            frame.to_csv(cache_path, index=False, compression={"method": "gzip", "mtime": 0})
            save_json(audit_path, {"training": audit})
        frames[candidate.name] = frame
        audits[candidate.name] = audit
        print(f"fold={season} candidate={candidate.name} seconds={time.monotonic()-started:.1f}", flush=True)
    for name, members in ENSEMBLES.items():
        combined = frames[members[0]].copy()
        for member in members[1:]:
            if not combined.match_id.equals(frames[member].match_id):
                raise ValueError("Ensemble prediction identities differ")
        combined[PROBS + ["p_binary_draw"]] = np.mean(
            [frames[m][PROBS + ["p_binary_draw"]].to_numpy() for m in members], axis=0)
        frames[name] = combined
    for name, frame in frames.items():
        policies = (*POLICIES, "production_fixed") if name == "current" else POLICIES
        for policy in policies:
            key = f"{name}__{policy}"
            decisions[key] = fit_betting_policy(frame[frame.season == season - 1], policy)
            bets[key] = apply_betting_policy(frame[frame.season == season], decisions[key])
    fold_audit = {"training_max_season": int(train.season.max()), "validation_season": season - 1,
                  "test_season": season, "training_max_date": train.date.max().isoformat(),
                  "validation_min_date": validation.date.min().isoformat(), "test_min_date": test.date.min().isoformat(),
                  "models": audits, "decisions": decisions}
    save_json(output / f"fold_{season}.json", fold_audit)
    return {n: f[f.season == season].copy() for n, f in frames.items()}, bets, fold_audit


def build_report(output: Path, predictions: dict, bets: dict, selection: dict, manifest: dict) -> dict:
    prediction_report = {}
    for name, frame in predictions.items():
        prediction_report[name] = {
            "all_folds": prediction_metrics(frame),
            "confirmation_2024_2025": prediction_metrics(frame[frame.season >= 2024]),
            "season_2025": prediction_metrics(frame[frame.season == 2025]),
        }
    portfolios = {}
    for name, frame in bets.items():
        portfolios[name] = {"all_folds": summarize_bets(frame),
                            "confirmation_2024_2025": summarize_bets(frame[frame.season >= 2024]),
                            "season_2025": summarize_bets(frame[frame.season == 2025])}
    report = {"manifest": manifest, "selection": selection, "prediction_results": prediction_report,
              "portfolio_results": portfolios,
              "limitations": [
                  "2014-2025 data were already explored in earlier experiments; no newly untouched season exists here.",
                  "Every fold respects train/validation/test chronology, but reused historic strategy definitions can bias early folds.",
                  "Intervals are descriptive and are not adjusted for selecting among many models and betting policies.",
                  "Opening odds are assumed available and executable; no fees, limits or live slippage are modelled.",
                  "Prediction accuracy and betting return are different objectives; one need not improve with the other.",
                  "Zero bets is reported as zero evidence, never as zero-percent return.",
              ]}
    save_json(output / "report.json", report)
    rows = []
    for name, values in portfolios.items():
        rows.append({"name": name, **{f"all_{k}": values["all_folds"].get(k) for k in ("bets", "roi", "profit_units")},
                     **{f"confirmation_{k}": values["confirmation_2024_2025"].get(k) for k in ("bets", "roi", "profit_units")},
                     **{f"2025_{k}": values["season_2025"].get(k) for k in ("bets", "roi", "profit_units")}})
    pd.DataFrame(rows).to_csv(output / "leaderboard.csv", index=False)
    all_bets = pd.concat([frame.assign(portfolio=name) for name, frame in bets.items()], ignore_index=True)
    all_bets.to_csv(output / "all_test_bets.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="train/dataset_home.csv")
    parser.add_argument("--output", default="train/output/research_v2_2026_09_05")
    parser.add_argument("--threads", type=int, default=2,
                        help="XGBoost/OpenMP threads. 0 preserves original native thread defaults.")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(args.dataset)
    frozen = output / "dataset_2014_2025.csv.gz"
    manifest_path = output / "manifest.json"
    current_sources = {name: file_hash(ROOT / name) for name in SOURCE_FILES}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("training_threads", 2) != args.threads:
            raise ValueError("Thread configuration changed: use a separate experiment directory")
        if manifest["source_sha256"] != current_sources or manifest["dataset_sha256"] != file_hash(frozen):
            raise ValueError("Experiment changed: use a new output directory to preserve the recorded experiment")
        dataset = pd.read_csv(frozen, parse_dates=["date"])
    else:
        dataset = pd.read_csv(source, parse_dates=["date"])
        dataset = dataset[dataset.target.notna() & dataset.season.between(2014, 2025)].copy()
        dataset["target"] = dataset.target.astype(int)
        if dataset.match_id.duplicated().any():
            raise ValueError("Duplicate fixtures in research dataset")
        # Preserve training row order: subsampled boosted trees depend on it.
        # Reordering the same data can change the seed-42 reference bets.
        dataset = dataset.reset_index(drop=True)
        dataset.to_csv(frozen, index=False, compression={"method": "gzip", "mtime": 0})
        manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "dataset_sha256": file_hash(frozen), "source_dataset_sha256": file_hash(source),
                    "source_sha256": current_sources, "rows": len(dataset), "excluded_seasons": [2026],
                    "training_threads": args.threads, "logical_cpu_count": os.cpu_count(),
                    "native_threadpools": [{"api": p["internal_api"], "threads": p["num_threads"]} for p in threadpool_info()],
                    "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                                "sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
                    "candidates": [asdict(c) for c in CANDIDATES], "ensembles": ENSEMBLES, "policies": POLICIES,
                    "development_folds": list(range(2019, 2024)), "confirmation_folds": [2024, 2025],
                    "selection_rule": "At least 150 development bets, three profitable seasons, positive pooled ROI; maximize day-bootstrap lower bound.",
                    "production_modified": False}
        save_json(manifest_path, manifest)
        dataset = pd.read_csv(frozen, parse_dates=["date"])
    manifest_id = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:20]
    prediction_parts, bet_parts = {}, {}
    selection = {}
    with (nullcontext() if args.threads == 0 else threadpool_limits(limits=args.threads)):
        for season in range(2019, 2026):
            if season == 2024:
                combined = {n: pd.concat(f, ignore_index=True) for n, f in bet_parts.items()}
                chosen, ranking = choose_candidate(combined)
                selection = {"chosen_on_development": chosen, "selection_through_season": 2023,
                             "recorded_before_confirmation_at_utc": datetime.now(timezone.utc).isoformat(),
                             "development_ranking": ranking}
                save_json(output / "selection_before_confirmation.json", selection)
                print(f"DEVELOPMENT SELECTION: {chosen}", flush=True)
            prediction, bets, _ = run_fold(dataset, season, output, manifest_id, threads=args.threads)
            for name, frame in prediction.items():
                prediction_parts.setdefault(name, []).append(frame)
            for name, frame in bets.items():
                bet_parts.setdefault(name, []).append(frame)
            print(f"FOLD {season} COMPLETE", flush=True)
        predictions = {n: pd.concat(f, ignore_index=True) for n, f in prediction_parts.items()}
        bets = {n: pd.concat(f, ignore_index=True) for n, f in bet_parts.items()}
        report = build_report(output, predictions, bets, selection, manifest)
    for name in [BASELINE, selection.get("chosen_on_development")]:
        if name:
            print(json.dumps({"portfolio": name, **report["portfolio_results"][name]}, ensure_ascii=False), flush=True)
    print(f"REPORT {output / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
