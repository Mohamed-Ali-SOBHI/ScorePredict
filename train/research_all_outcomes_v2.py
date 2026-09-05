"""Secondary research: diversify draw-only betting to home/draw/away, one bet per match.

This explicitly changes the betting universe and is not the original draw strategy.
Predictions come from the same frozen, chronologically separated research folds.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from train.research_challengers_v2 import CANDIDATES, ENSEMBLES, PROBS, file_hash, save_json, summarize_bets

POLICIES = ("fixed_05", "fixed_10", "validation_cautious")
ODDS = ["market_away_win_odds_open", "market_draw_odds_open", "market_home_win_odds_open"]
MARKET = ["market_away_prob_open", "market_draw_prob_open", "market_home_prob_open"]


def load_frame(folder: Path, name: str, year: int) -> pd.DataFrame:
    if name in ENSEMBLES:
        members = [load_frame(folder, m, year) for m in ENSEMBLES[name]]
        result = members[0].copy()
        for other in members[1:]:
            if not result.match_id.equals(other.match_id):
                raise ValueError("Ensemble fixture identities differ")
        result[PROBS] = np.mean([f[PROBS].to_numpy() for f in members], axis=0)
        return result
    paths = list((folder / "prediction_cache").glob(f"*/{year}_{name}.csv.gz"))
    if len(paths) != 1:
        raise ValueError(f"Missing or ambiguous cache {name} {year}")
    return pd.read_csv(paths[0], parse_dates=["date"]).sort_values("match_id").reset_index(drop=True)


def offers(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    p, odds, market = (result[cols].to_numpy() for cols in (PROBS, ODDS, MARKET))
    ev = p * odds - 1
    eligible = np.isfinite(ev) & (odds >= 1.5) & (odds < 8.0)
    best = np.where(eligible, ev, -np.inf).argmax(axis=1)
    at = np.arange(len(frame)), best
    result["selected_class"] = best
    result["selected_odds"] = odds[at]
    result["expected_value"] = np.where(eligible[at], ev[at], -np.inf)
    result["edge"] = (p - market)[at]
    return result


def fit_filter(validation: pd.DataFrame, policy: str) -> dict | None:
    if policy in {"fixed_05", "fixed_10"}:
        return {"ev": .05 if policy == "fixed_05" else .10, "edge": 0.0}
    if policy != "validation_cautious":
        raise ValueError(policy)
    validation = offers(validation)
    best = None
    for ev in (.0, .02, .05, .075, .10, .15, .20, .30, .40):
        for edge in (.0, .02):
            chosen = validation[(validation.expected_value > ev) & (validation.edge >= edge)]
            if len(chosen) < 80:
                continue
            profits = np.where(chosen.target == chosen.selected_class, chosen.selected_odds - 1, -1)
            score = float(profits.mean() - profits.std(ddof=1) / np.sqrt(len(profits)))
            if score <= 0:
                continue
            rank = (score, float(profits.sum()), len(profits))
            if best is None or rank > best[0]:
                best = (rank, {"ev": ev, "edge": edge, "validation_bets": len(chosen),
                               "validation_roi": float(profits.mean())})
    return best[1] if best else None


def apply_filter(test: pd.DataFrame, setting: dict | None) -> pd.DataFrame:
    rows = offers(test)
    if setting is None:
        return rows.iloc[:0].copy()
    return rows[(rows.expected_value > setting["ev"]) & (rows.edge >= setting["edge"])].copy()


def summary(bets: pd.DataFrame) -> dict:
    if bets.empty:
        return summarize_bets(bets)
    # Reuse the tested identical-stake accounting, mapping correct/incorrect
    # predictions to its expected binary win indicator. Preserve actual targets.
    accounting = bets.assign(target=np.where(bets.target == bets.selected_class, 1, 0))
    value = summarize_bets(accounting)
    value["by_outcome"] = {label: summarize_bets(accounting[accounting.selected_class == index], bootstrap=False)
                           for index, label in enumerate(("away", "draw", "home"))}
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="train/output/research_v2_2026_09_05")
    args = parser.parse_args()
    folder = Path(args.folder)
    source_manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    protocol_path = folder / "all_outcomes_protocol.json"
    if not protocol_path.exists():
        save_json(protocol_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                                 "source_sha256": file_hash(Path(__file__)),
                                 "dataset_sha256": source_manifest["dataset_sha256"],
                                 "selection": "2019-2023 only; at least 150 bets, 3 profitable seasons, positive return; highest lower day-bootstrap bound",
                                 "confirmation": [2024, 2025], "odds": [1.5, 8.0],
                                 "policies": POLICIES, "one_bet_per_match": True})
    else:
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if protocol["source_sha256"] != file_hash(Path(__file__)):
            raise ValueError("All-outcomes protocol has changed")
    names = [c.name for c in CANDIDATES] + list(ENSEMBLES)
    accumulated, audits = {}, {}
    for year in range(2019, 2024):
        for name in names:
            frame = load_frame(folder, name, year)
            for policy in POLICIES:
                key = f"{name}__{policy}"
                setting = fit_filter(frame[frame.season == year-1], policy)
                audits[f"{key}:{year}"] = setting
                accumulated.setdefault(key, []).append(apply_filter(frame[frame.season == year], setting))
    development_ranking = []
    for name, parts in accumulated.items():
        value = summary(pd.concat(parts, ignore_index=True))
        eligible = value["bets"] >= 150 and value["positive_seasons"] >= 3 and value["roi"] > 0
        development_ranking.append({"name": name, "eligible": eligible, "development": value})
    development_ranking.sort(key=lambda r: (r["eligible"], r["development"].get("day_block_roi_interval_95pct", [-1])[0]), reverse=True)
    chosen = next((r["name"] for r in development_ranking if r["eligible"]), None)
    save_json(folder / "all_outcomes_selection.json", {"chosen": chosen, "ranking": development_ranking,
                                                       "recorded_before_confirmation_at_utc": datetime.now(timezone.utc).isoformat()})
    for year in (2024, 2025):
        for name in names:
            frame = load_frame(folder, name, year)
            for policy in POLICIES:
                key = f"{name}__{policy}"
                setting = fit_filter(frame[frame.season == year-1], policy)
                audits[f"{key}:{year}"] = setting
                accumulated[key].append(apply_filter(frame[frame.season == year], setting))
    results = {}
    for name, parts in accumulated.items():
        all_bets = pd.concat(parts, ignore_index=True)
        results[name] = {"all_folds": summary(all_bets),
                         "confirmation_2024_2025": summary(all_bets[all_bets.season >= 2024]),
                         "season_2025": summary(all_bets[all_bets.season == 2025])}
    save_json(folder / "all_outcomes_report.json", {"chosen_on_development": chosen, "results": results,
                                                   "decisions_by_fold": audits, "production_modified": False,
                                                   "scope": "Three outcomes, odds 1.5-8, same three leagues; different from draw-only reference"})
    print(json.dumps({"chosen": chosen, "top_development": [(r['name'],r['eligible'],r['development']['roi']) for r in development_ranking[:5]]}))
    if chosen:
        print(json.dumps(results[chosen]))


if __name__ == "__main__":
    main()
