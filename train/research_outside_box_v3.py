"""Exploratory alternatives: goal counts, past OOF errors, model disagreement.

No production writes. Same frozen data and native-thread reference as research v2.
Common comparison folds 2021-2025; selection on 2021-2023 precedes scoring 2024-2025.
These seasons have already been explored: this is not prospective validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import importlib.metadata
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
from threadpoolctl import threadpool_info

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from train.research_all_outcomes_v2 import load_frame
from train.research_challengers_v2 import (
    PROBS, LEAGUES, POLICIES, apply_betting_policy, choose_candidate, features,
    file_hash, fit_betting_policy, market, save_json, summarize_bets, temporal_split,
)
from train.evaluate_model_challengers import prediction_metrics

MEMBERS = ("unweighted", "unweighted_ensemble", "shallow_recent", "market_residual")
GOAL_VARIANTS = ("poisson_linear", "poisson_boosted", "poisson_market_blend")
ROBUST_VARIANTS = ("runtime_average", "runtime_cautious", "diversity_cautious")


def goal_probabilities(home: np.ndarray, away: np.ndarray) -> np.ndarray:
    """Independent goal counts; class order is away/draw/home, not score order."""
    home = np.clip(np.asarray(home), .05, 8)
    away = np.clip(np.asarray(away), .05, 8)
    goals = np.arange(41)
    hp = poisson.pmf(goals[None, :], home[:, None])
    ap = poisson.pmf(goals[None, :], away[:, None])
    draw = (hp * ap).sum(axis=1)
    home_win = (hp * (np.cumsum(ap, axis=1) - ap)).sum(axis=1)
    away_win = (ap * (np.cumsum(hp, axis=1) - hp)).sum(axis=1)
    probabilities = np.column_stack([away_win, draw, home_win])
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def replace_draw(frame: pd.DataFrame, probability: np.ndarray) -> pd.DataFrame:
    result = frame.copy()
    p = np.clip(np.asarray(probability), .001, .999)
    non_draw = result[["p_away", "p_home"]].to_numpy()
    non_draw /= non_draw.sum(axis=1, keepdims=True)
    result[["p_away", "p_home"]] = non_draw * (1 - p[:, None])
    result["p_draw"] = p
    result["p_binary_draw"] = p
    return result


def checked_goals(raw: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    """Final scores are labels only; fail on ambiguous scores or result mismatch."""
    columns = ["match_id", "team_goals", "opponent_goals"]
    raw = raw[columns].drop_duplicates()
    if raw.match_id.duplicated().any():
        raise ValueError("Conflicting actual scores for the same match")
    merged = dataset[["match_id", "target"]].merge(raw, on="match_id", how="left", validate="one_to_one")
    if merged[columns[1:]].isna().any().any():
        raise ValueError("Missing goal labels")
    scores = merged[columns[1:]].to_numpy()
    if (scores < 0).any() or (scores != np.floor(scores)).any():
        raise ValueError("Invalid actual goals")
    target = np.where(scores[:, 0] > scores[:, 1], 2, np.where(scores[:, 0] == scores[:, 1], 1, 0))
    if not np.array_equal(target, merged.target.to_numpy()):
        raise ValueError("Goal labels disagree with frozen result labels")
    return merged[columns]


def freeze_goals(dataset: pd.DataFrame, output: Path) -> pd.DataFrame:
    path = output / "goal_labels.csv.gz"
    if path.exists():
        return checked_goals(pd.read_csv(path), dataset)
    parts, sources = [], {}
    for source in sorted((ROOT / "Data").glob("*/*.csv")):
        if not source.name[:4].isdigit() or not 2014 <= int(source.name[:4]) <= 2025:
            continue
        raw = pd.read_csv(source, usecols=["match_id", "is_home", "team_goals", "opponent_goals"])
        home = raw.is_home.astype(str).str.lower().eq("true")
        parts.append(raw.loc[home])
        sources[str(source.relative_to(ROOT))] = file_hash(source)
    goals = checked_goals(pd.concat(parts, ignore_index=True), dataset)
    goals.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    save_json(output / "goal_sources.json", sources)
    return goals


def fit_goals(train: pd.DataFrame, score: pd.DataFrame, family: str) -> np.ndarray:
    x, z = features(train, enriched=True), features(score, enriched=True)
    predictions = []
    for target in ("team_goals", "opponent_goals"):
        if family == "poisson_linear":
            model = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                                  StandardScaler(), PoissonRegressor(alpha=1, max_iter=500, tol=1e-7))
            model.fit(x, train[target])
        else:
            model = XGBRegressor(objective="count:poisson", n_estimators=200, max_depth=2,
                                 learning_rate=.03, min_child_weight=40, reg_lambda=30,
                                 subsample=.85, colsample_bytree=.85, random_state=42, n_jobs=0)
            weight = .9 ** (train.season.max() - train.season.to_numpy())
            model.fit(x, train[target], sample_weight=weight)
        predictions.append(model.predict(z))
    return goal_probabilities(*predictions)


def cached_members(folder: Path, year: int) -> dict[str, pd.DataFrame]:
    frames = {name: load_frame(folder, name, year) for name in MEMBERS}
    reference = frames[MEMBERS[0]]
    for frame in frames.values():
        if not reference.match_id.equals(frame.match_id):
            raise ValueError("Member fixtures do not align")
    return frames


def meta_features(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Only pre-match forecast information, never actual outcomes or scores."""
    reference = frames[MEMBERS[0]]
    data = {}
    for name, frame in frames.items():
        for col in (*PROBS, "p_binary_draw"):
            data[f"{name}_{col}"] = frame[col].to_numpy()
    for index, col in enumerate(PROBS):
        data[f"market_{col}"] = market(reference)[:, index]
    data["draw_odds"] = reference.market_draw_odds_open.to_numpy()
    data["draw_disagreement"] = np.std([frame.p_draw.to_numpy() for frame in frames.values()], axis=0)
    data["reference_edge"] = reference.p_draw.to_numpy() - market(reference)[:, 1]
    for league in LEAGUES:
        data[f"league_{league}"] = (reference.league == league).to_numpy(dtype=float)
    return pd.DataFrame(data, index=reference.index)


def earlier_oof(folder: Path, through: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrices, labels = [], []
    for season in range(2018, through + 1):
        members = cached_members(folder, max(2019, season))
        members = {name: frame[frame.season == season].reset_index(drop=True) for name, frame in members.items()}
        matrices.append(meta_features(members))
        labels.append(members[MEMBERS[0]][["match_id", "season", "date", "target"]])
    x, y = pd.concat(matrices, ignore_index=True), pd.concat(labels, ignore_index=True)
    if y.match_id.duplicated().any() or y.season.max() > through:
        raise ValueError("Meta learning contains repeated fixtures or future labels")
    return x, y


def make_fold(dataset: pd.DataFrame, folder: Path, perturbation: Path, output: Path, year: int) -> tuple[dict, dict]:
    train, validation, test = temporal_split(dataset, year)
    members = cached_members(folder, year)
    reference = members["unweighted"]
    score = pd.concat([validation, test]).set_index("match_id").loc[reference.match_id].reset_index()
    frames, audit = {"unweighted_reference": reference}, {"year": year, "train_through": year-2, "filter_on": year-1}
    cache = output / "prediction_cache"
    cache.mkdir(exist_ok=True)
    for family in GOAL_VARIANTS[:2]:
        path = cache / f"{year}_{family}.csv.gz"
        if path.exists():
            frame = pd.read_csv(path, parse_dates=["date"])
        else:
            frame = reference.copy()
            frame[PROBS] = fit_goals(train, score, family)
            frame["p_binary_draw"] = frame.p_draw
            frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
        if not frame.match_id.equals(reference.match_id):
            raise ValueError("Goal predictions do not align")
        frames[family] = frame
    blended = reference.copy()
    blended[PROBS] = .5 * frames["poisson_boosted"][PROBS].to_numpy() + .5 * market(reference)
    blended["p_binary_draw"] = blended.p_draw
    frames["poisson_market_blend"] = blended

    altered = load_frame(perturbation, "unweighted", year)
    if not altered.match_id.equals(reference.match_id):
        raise ValueError("Thread perturbation predictions do not align")
    for name, sources, penalty in (("runtime_average", [reference, altered], 0),
                                    ("runtime_cautious", [reference, altered], 1),
                                    ("diversity_cautious", list(members.values()), .5)):
        signals = np.array([np.minimum(f.p_draw, f.p_binary_draw) for f in sources])
        frames[name] = replace_draw(reference, signals.mean(axis=0) - penalty * signals.std(axis=0))

    x, labels = earlier_oof(folder, through=year-2)
    if labels.date.max() >= reference.date.min() or set(labels.match_id) & set(reference.match_id):
        raise ValueError("Meta training overlaps its validation or test")
    meta = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=.03, max_iter=1000, solver="lbfgs"))
    meta.fit(x, (labels.target == 1).astype(int))
    frames["meta_draw"] = replace_draw(reference, meta.predict_proba(meta_features(members))[:, 1])
    audit["meta_training"] = {"rows": len(labels), "through": int(labels.season.max()),
                               "last_date": labels.date.max().isoformat(), "features": list(x.columns)}
    bets, decisions = {}, {}
    for name, frame in frames.items():
        for policy in (("legacy",) if name == "unweighted_reference" else POLICIES):
            key = f"{name}__{policy}"
            decision = fit_betting_policy(frame[frame.season == year-1], policy)
            decisions[key] = decision
            bets[key] = apply_betting_policy(frame[frame.season == year], decision)
    reference_bets = bets["unweighted_reference__legacy"]
    meta_ev = frames["meta_draw"].set_index("match_id").p_draw * reference.set_index("match_id").market_draw_odds_open - 1
    bets["meta_veto_reference"] = reference_bets[reference_bets.match_id.map(meta_ev) > 0].copy()
    audit["filters"] = decisions
    save_json(output / f"fold_{year}.json", audit)
    return bets, {name: frame[frame.season == year].copy() for name, frame in frames.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default="train/output/research_v2_native_2026_09_05")
    parser.add_argument("--perturbation", default="train/output/research_v2_2026_09_05")
    parser.add_argument("--output", default="train/output/research_outside_box_v3_2026_09_05")
    args = parser.parse_args()
    folder, perturbation, output = map(Path, (args.folder, args.perturbation, args.output))
    output.mkdir(parents=True, exist_ok=True)
    dataset_path = folder / "dataset_2014_2025.csv.gz"
    if file_hash(dataset_path) != file_hash(perturbation / "dataset_2014_2025.csv.gz"):
        raise ValueError("Reference and runtime perturbation used different data")
    dataset = pd.read_csv(dataset_path, parse_dates=["date"])
    goals = freeze_goals(dataset, output)
    dataset = dataset.merge(goals, on="match_id", how="left", sort=False, validate="one_to_one")
    protocol_path = output / "protocol.json"
    sources = [Path(__file__), ROOT / "train/research_challengers_v2.py", ROOT / "train/research_all_outcomes_v2.py"]
    hashes = {str(p.relative_to(ROOT)): file_hash(p) for p in sources}
    if protocol_path.exists():
        old = json.loads(protocol_path.read_text(encoding="utf-8"))
        if old["source_sha256"] != hashes or old["goal_labels_sha256"] != file_hash(output / "goal_labels.csv.gz"):
            raise ValueError("Out-of-box protocol changed; use a new output folder")
    else:
        save_json(protocol_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                                  "source_sha256": hashes, "dataset_sha256": file_hash(dataset_path),
                                  "runtime": {name: importlib.metadata.version(name) for name in
                                              ("numpy", "pandas", "scipy", "scikit-learn", "xgboost", "joblib", "threadpoolctl")},
                                  "native_threadpools": [{"api": p["internal_api"], "threads": p["num_threads"]}
                                                         for p in threadpool_info()],
                                  "goal_labels_sha256": file_hash(output / "goal_labels.csv.gz"),
                                  "development": [2021, 2022, 2023], "confirmation": [2024, 2025],
                                  "models": [*GOAL_VARIANTS, *ROBUST_VARIANTS, "meta_draw", "meta_veto_reference"],
                                  "selection": "At least 150 bets and 3 profitable development seasons; best lower day-block bound",
                                  "threads": "Native defaults for goal models; saved native/2-thread predictions for perturbations",
                                  "limitations": ["All historic seasons already explored; no prospective claim",
                                                  "Intervals not corrected for multiple comparisons", "Opening odds assumed executable",
                                                  "Independent Poisson ignores score correlation; uncertainty penalties are heuristic"],
                                  "production_modified": False})
    accumulated, forecasts = {}, {}
    chosen = None
    for year in range(2021, 2026):
        bets, predictions = make_fold(dataset, folder, perturbation, output, year)
        for name, frame in bets.items():
            accumulated.setdefault(name, []).append(frame)
        for name, frame in predictions.items():
            forecasts.setdefault(name, []).append(frame)
        print(f"Completed outside-box fold {year}", flush=True)
        if year == 2023:
            chosen, ranking = choose_candidate({n: pd.concat(p, ignore_index=True) for n, p in accumulated.items()})
            save_json(output / "selection_before_confirmation.json", {"chosen": chosen, "ranking": ranking,
                                                                       "recorded_at_utc": datetime.now(timezone.utc).isoformat()})
    summaries, prediction_results, rows = {}, {}, []
    periods = {"development_2021_2023": (2021, 2023), "confirmation_2024_2025": (2024, 2025),
               "season_2025": (2025, 2025), "all_2021_2025": (2021, 2025)}
    for name, parts in accumulated.items():
        bets = pd.concat(parts, ignore_index=True)
        summaries[name] = {p: summarize_bets(bets[bets.season.between(*years)]) for p, years in periods.items()}
        rows.append({"name": name, **{f"{p}_{k}": s.get(k) for p, s in summaries[name].items() for k in ("bets", "roi", "profit_units")}})
    for name, parts in forecasts.items():
        predictions = pd.concat(parts, ignore_index=True)
        prediction_results[name] = {p: prediction_metrics(predictions[predictions.season.between(*years)]) for p, years in periods.items()}
    save_json(output / "report.json", {"selected_before_confirmation": chosen, "portfolios": summaries,
                                       "prediction_results": prediction_results, "production_modified": False})
    pd.DataFrame(rows).to_csv(output / "leaderboard.csv", index=False)
    pd.concat([pd.concat(parts).assign(portfolio=name) for name, parts in accumulated.items()], ignore_index=True).to_csv(
        output / "all_test_bets.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    print(json.dumps({"selected_before_confirmation": chosen, "result": summaries.get(chosen)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
