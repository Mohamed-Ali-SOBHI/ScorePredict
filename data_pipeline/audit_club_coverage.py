"""Fail closed when current sporting histories disappear before live inference.

Compare the exact scrape snapshot with persisted rows, the current registry and
the causal feature builder. Missing optional market/shots data is reported
separately. No invented observations or model/strategy changes are made here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from data_pipeline.market_data import normalize_team_name
from data_pipeline.team_registry import EXPECTED_TEAM_COUNTS, read_registry
from train.make_dataset import (
    add_team_prematch_features, build_home_perspective_dataset, load_team_match_rows,
    WINDOWS_DEFAULT,
)


FIELDS = {
    "team_xG": ("xG",), "opponent_xG": ("xGA",),
    "team_goals": ("scored",), "opponent_goals": ("missed",),
    "team_deep": ("deep",), "opponent_deep": ("deep_allowed",),
    "team_xpts": ("xpts",), "team_npxG": ("npxG",),
    "opponent_npxG": ("npxGA",),
    "team_ppda_att": ("ppda", "att"), "team_ppda_def": ("ppda", "def"),
    "opponent_ppda_att": ("ppda_allowed", "att"),
    "opponent_ppda_def": ("ppda_allowed", "def"),
}
OPTIONAL = ["team_shots", "opponent_shots", "team_win_odds_open",
            "draw_odds_open", "opponent_win_odds_open"]


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def source_value(row, keys):
    for key in keys:
        row = row.get(key) if isinstance(row, dict) else None
    return number(row)


def audit_league(payload, registry, rows, *, league, season, expected_count):
    """Audit one league without normalizing away unrecognized source clubs."""
    errors, clubs = [], []
    raw_teams = payload.get("teams", {})
    entries = raw_teams.items() if isinstance(raw_teams, dict) else ((None, t) for t in raw_teams)
    source = {str(t.get("id") or t.get("team_id") or key): t for key, t in entries}
    fixtures = payload.get("dates")
    if not isinstance(fixtures, (list, dict)):
        errors.append("Source fixture collection missing")
        fixtures = []
    fixtures = list(fixtures.values()) if isinstance(fixtures, dict) else fixtures
    completed = [f for f in fixtures if f.get("isResult") is True]
    fixture_ids = [str(f.get("id")) for f in completed]
    if len(set(fixture_ids)) != len(fixture_ids):
        errors.append("Duplicate completed source fixtures")
    expected = {}
    fixture_titles = {}
    for fixture in fixtures:
        for side in ("h", "a"):
            fixture_titles[str(fixture[side]["id"])] = fixture[side].get("title", "")
    for fixture in completed:
        for side, other in (("h", "a"), ("a", "h")):
            tid = str(fixture[side]["id"])
            key = (tid, str(fixture["datetime"]))
            if key in expected:
                errors.append(f"Duplicate fixture team/date: {key}")
            expected[key] = (str(fixture[other]["id"]), side, fixture)

    registered = {str(t["team_id"]): t for t in registry}
    names = [normalize_team_name(t["team_name"]) for t in registry]
    if len(registry) != expected_count or len(registered) != expected_count or len(set(names)) != expected_count:
        errors.append(f"Expected {expected_count} unique registered clubs; got {len(registry)}")
    active_ids = {tid for tid, _ in expected}
    for tid in sorted(active_ids - set(registered)):
        errors.append(f"Played club absent from registry: {tid} {fixture_titles.get(tid)}")
    # A source club with history cannot be silently discarded by an allow-list.
    for tid, team in source.items():
        if team.get("history") and tid not in registered:
            errors.append(f"Source history excluded: {tid} {team.get('title')}")

    persisted = {}
    for row in rows:
        key = (str(row.get("team_id")), str(row.get("date")))
        if key in persisted:
            errors.append(f"Duplicate saved team/date: {key}")
        persisted[key] = row
    if set(persisted) != set(expected):
        errors.append(f"Saved coverage differs: missing={sorted(set(expected)-set(persisted))}, extra={sorted(set(persisted)-set(expected))}")

    for tid, registered_team in registered.items():
        title = registered_team["team_name"]
        team = source.get(tid, {})
        source_title = team.get("title") or fixture_titles.get(tid)
        if source_title and normalize_team_name(source_title) != normalize_team_name(title):
            errors.append(f"Club identity mismatch: {tid}: {title} / {source_title}")
        history = team.get("history") or []
        keys = [(tid, str(h.get("date"))) for h in history]
        team_expected = {k for k in expected if k[0] == tid}
        if set(keys) != team_expected or len(keys) != len(set(keys)):
            errors.append(f"{title}: source history does not match completed fixtures")
        team_rows = [r for (rtid, _), r in persisted.items() if rtid == tid]
        clubs.append({"team_id": tid, "team_name": title,
                      "completed_matches": len(team_expected), "source_rows": len(history),
                      "saved_rows": len(team_rows),
                      "optional_missing": {c: sum(number(r.get(c)) is None for r in team_rows) for c in OPTIONAL}})
        for h in history:
            key = (tid, str(h.get("date")))
            actual = persisted.get(key)
            fixture_info = expected.get(key)
            if not fixture_info or actual is None:
                continue
            opponent, side, fixture = fixture_info
            ids = sorted([tid, opponent])
            match_id = f"{league} {season}_{ids[0]}_{ids[1]}_{key[1]}"
            if (str(actual.get("opponent_id")) != opponent or actual.get("match_id") != match_id
                    or str(actual.get("is_home")).lower() != str(side == "h").lower()
                    or h.get("h_a") != side):
                errors.append(f"{title} {key[1]}: incorrect opponent, venue or match id")
            if normalize_team_name(actual.get("team_name", "")) != normalize_team_name(title):
                errors.append(f"{title} {key[1]}: saved team name mismatch")
            expected_opponent = fixture_titles.get(opponent, "")
            if normalize_team_name(actual.get("opponent_name", "")) != normalize_team_name(expected_opponent):
                errors.append(f"{title} {key[1]}: saved opponent name mismatch")
            goals, conceded = number(h.get("scored")), number(h.get("missed"))
            result = None if goals is None or conceded is None else "w" if goals > conceded else "l" if goals < conceded else "d"
            if result is None or h.get("result") != result or actual.get("result") != result:
                errors.append(f"{title} {key[1]}: invalid result")
            for column, path in FIELDS.items():
                value, saved = source_value(h, path), number(actual.get(column))
                if value is None or saved is None or not math.isclose(value, saved, rel_tol=1e-7, abs_tol=1e-7):
                    errors.append(f"{title} {key[1]}: missing/changed {column}")
            other = "a" if side == "h" else "h"
            for source_field, fixture_field, fixture_side in (("scored", "goals", side), ("missed", "goals", other), ("xG", "xG", side), ("xGA", "xG", other)):
                left = number(h.get(source_field))
                right = number(fixture.get(fixture_field, {}).get(fixture_side))
                if left is None or right is None or not math.isclose(left, right, abs_tol=0.0001):
                    errors.append(f"{title} {key[1]}: fixture/history mismatch for {source_field}")
    return {"league": league, "clubs": clubs, "completed_matches": len(completed),
            "saved_rows": len(rows), "errors": errors}


def audit_features(frame):
    """Warm-up NaNs are legitimate only before a team's first observation."""
    errors = []
    for side, count_column in (("team", "matches_played_in_season_before"),
                               ("opponent", "opponent_matches_played_in_season_before")):
        played = pd.to_numeric(frame[count_column], errors="coerce")
        if played.isna().any():
            errors.append(f"Missing {count_column}")
        for metric in ("xG", "xG_against", "deep", "deep_against", "ppda_att", "ppda_def"):
            column = f"{side}_{metric}_last_1"
            values = pd.to_numeric(frame[column], errors="coerce")
            bad = (played > 0) & (~values.map(lambda v: math.isfinite(v)) | (values < 0))
            if bad.any():
                errors.append(f"Missing/invalid causal feature {column}: {frame.loc[bad, 'match_id'].tolist()}")
    return errors


def audit_upcoming(raw, future, bundles, output):
    """Check actual pre-match inputs and retain their missingness, before scoring."""
    errors = audit_features(future)
    clubs = []
    feature_columns = sorted({column for bundle in bundles.values()
                              for column in bundle.feature_cols + (bundle.secondary_feature_cols or [])})
    missing_columns = sorted(set(feature_columns) - set(future.columns))
    if missing_columns:
        errors.append(f"Missing model input columns: {missing_columns}")
    for _, match in future.iterrows():
        for id_column, name_column, count_column in (
            ("team_id", "team_name", "matches_played_in_season_before"),
            ("opponent_id", "opponent_name", "opponent_matches_played_in_season_before"),
        ):
            history = raw[(raw["league"] == match["league"])
                          & (raw["season"] == match["season"])
                          & (raw["team_id"].astype(str) == str(match[id_column]))
                          & (raw["date"] < match["date"])]
            if number(match[count_column]) != len(history):
                errors.append(f"{match['match_id']} {match[name_column]}: model history count differs from saved observations")
            clubs.append({"match_id": match["match_id"], "club": match[name_column],
                          "history_rows": len(history), "model_history_rows": number(match[count_column])})
    missing_values = {c: int(future[c].isna().sum()) for c in feature_columns
                      if c in future and future[c].isna().any()}
    for column in feature_columns:
        if column in future:
            numeric = pd.to_numeric(future[column], errors="coerce")
            if numeric.isin([float("inf"), -float("inf")]).any():
                errors.append(f"Infinite model input: {column}")
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed" if errors else "passed", "fixtures": len(future),
              "model_feature_count": len(feature_columns), "clubs": clubs,
              "missing_model_inputs": missing_values, "errors": errors}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise ValueError("Invalid upcoming sporting inputs: " + "; ".join(errors))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--data-dir", default="Data")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output", default="train/output/club_coverage_audit.json")
    args = parser.parse_args()
    registry = read_registry(args.data_dir)["teams"]
    reports = []
    for league, count in EXPECTED_TEAM_COUNTS.items():
        path = Path(args.source_dir) / f"{league}-{args.season}.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = []
        for csv in (Path(args.data_dir) / league).glob(f"{args.season} *.csv"):
            rows.extend(pd.read_csv(csv, dtype=str).to_dict("records"))
        league_registry = [r for r in registry if r["league"] == league and int(r["season"]) == args.season]
        report = audit_league(payload, league_registry, rows, league=league, season=args.season, expected_count=count)
        report.update(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      captured_at=payload.get("captured_at"))
        reports.append(report)
    errors = [f"{r['league']}: {e}" for r in reports for e in r["errors"]]
    feature_summary = {}
    if not errors:
        # This is the same unfiltered raw loader/causal builder as live inference.
        raw = load_team_match_rows(args.data_dir)
        enriched = add_team_prematch_features(raw, windows=WINDOWS_DEFAULT)
        frame = build_home_perspective_dataset(enriched, windows=WINDOWS_DEFAULT)
        current = frame[frame["season"] == args.season]
        if len(current) != sum(r["completed_matches"] for r in reports):
            errors.append("Causal model dataset lost current-season matches")
        errors.extend(audit_features(current))
        feature_summary = {"matches": len(current), "columns_with_missing_values":
                           {c: int(n) for c, n in current.isna().sum().items() if n}}
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "season": args.season,
              "status": "failed" if errors else "passed", "leagues": reports,
              "causal_dataset": feature_summary, "errors": errors,
              "scope": "Current source fixture coverage, registry identities, saved sporting values and causal features. Optional market/shots and prior-season warm-up missingness are reported separately; source truth is not independently guaranteed."}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "clubs": sum(len(r["clubs"]) for r in reports),
                      "matches": sum(r["completed_matches"] for r in reports), "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
