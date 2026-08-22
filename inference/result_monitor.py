from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_pipeline.market_data import normalize_team_name
from data_pipeline.scrapper import get_league_data
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.sportytrader_client import DISPLAY_TIMEZONE, fetch_sportsdb_fixture_times, infer_season


FINAL_STATUSES = {"FT", "AET", "PEN", "AWD"}
OUTCOME_LABELS = {
    "draw": "Match nul",
    "home_win": "Victoire domicile",
    "away_win": "Victoire extérieur",
}
LEAGUE_LABELS = {
    "EPL": "Premier League",
    "La_liga": "La Liga",
    "Bundesliga": "Bundesliga",
    "Serie_A": "Serie A",
    "Ligue_1": "Ligue 1",
}
TERMINAL_RESULT_STATUSES = {"won", "lost", "void"}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "0.0", "false", "no", "none", "nan", "<na>"}


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if pd.notna(number) else default
    except (TypeError, ValueError):
        return default


def paris_datetime(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(DISPLAY_TIMEZONE).tz_localize(None)
    return timestamp


def result_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home_win"
    if home_score < away_score:
        return "away_win"
    return "draw"


def understat_finished_results(payload: dict[str, dict], *, league: str) -> pd.DataFrame:
    """Pair finished Understat team histories into home/away result rows."""
    histories: list[dict[str, Any]] = []
    for team in payload.values():
        team_name = str(team.get("title") or "").strip()
        if not team_name:
            continue
        for match in team.get("history") or []:
            if str(match.get("result") or "").lower() not in {"w", "d", "l"}:
                continue
            histories.append({"team_name": team_name, **match})

    rows: list[dict[str, Any]] = []
    for home in histories:
        if str(home.get("h_a")) != "h":
            continue
        opponent = next(
            (
                away
                for away in histories
                if str(away.get("h_a")) == "a"
                and str(away.get("date")) == str(home.get("date"))
                and _number(away.get("scored")) == _number(home.get("missed"))
                and _number(away.get("missed")) == _number(home.get("scored"))
                and abs(_number(away.get("xG")) - _number(home.get("xGA"))) < 0.01
                and abs(_number(away.get("xGA")) - _number(home.get("xG"))) < 0.01
            ),
            None,
        )
        if opponent is None:
            continue
        rows.append(
            {
                "league": league,
                "home_team_norm": normalize_team_name(home["team_name"]),
                "away_team_norm": normalize_team_name(opponent["team_name"]),
                "official_date": paris_datetime(home["date"]),
                "status": "FT",
                "home_score": int(_number(home.get("scored"))),
                "away_score": int(_number(home.get("missed"))),
                "result_source": "understat_finished_history",
            }
        )
    return pd.DataFrame(rows)


def due_prediction_mask(
    ledger: pd.DataFrame,
    *,
    now: pd.Timestamp,
    minimum_elapsed_minutes: int,
    portfolio_name: str,
) -> pd.Series:
    dates = ledger["date"].map(paris_datetime)
    statuses = ledger.get("result_status", pd.Series("pending", index=ledger.index)).astype(str).str.lower()
    recommended = ledger.get("recommended", pd.Series(False, index=ledger.index)).map(_truthy)
    portfolios = ledger.get("portfolio_name", pd.Series("", index=ledger.index)).astype(str)
    return (
        recommended
        & (portfolios == portfolio_name)
        & ~statuses.isin(TERMINAL_RESULT_STATUSES)
        & (dates + pd.Timedelta(minutes=minimum_elapsed_minutes) <= now)
    )


def settle_due_predictions(
    ledger: pd.DataFrame,
    results: pd.DataFrame,
    *,
    now: pd.Timestamp,
    minimum_elapsed_minutes: int = 105,
    portfolio_name: str = DEFAULT_PORTFOLIO_NAME,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Settle only officially finished matches; elapsed time alone is never enough."""
    updated = ledger.copy()
    if updated.empty:
        return updated, {"due": 0, "settled": 0, "still_running": 0, "unmatched": 0}

    due_mask = due_prediction_mask(
        updated,
        now=now,
        minimum_elapsed_minutes=minimum_elapsed_minutes,
        portfolio_name=portfolio_name,
    )
    due_indexes = list(updated.index[due_mask])
    counters = {"due": len(due_indexes), "settled": 0, "still_running": 0, "unmatched": 0}
    if not due_indexes:
        return updated, counters

    official = results.copy()
    if official.empty:
        counters["unmatched"] = len(due_indexes)
        return updated, counters
    official["official_date"] = pd.to_datetime(official["official_date"], errors="coerce", format="mixed")

    for index in due_indexes:
        row = updated.loc[index]
        kickoff = paris_datetime(row["date"])
        candidates = official[
            (official["league"].astype(str) == str(row.get("league")))
            & (official["home_team_norm"].astype(str) == normalize_team_name(row.get("team_name")))
            & (official["away_team_norm"].astype(str) == normalize_team_name(row.get("opponent_name")))
        ].copy()
        if not candidates.empty:
            candidates["distance"] = (candidates["official_date"] - kickoff).abs()
            candidates = candidates[candidates["distance"] <= pd.Timedelta(days=1)]
        if candidates.empty:
            counters["unmatched"] += 1
            continue

        final_candidates = candidates[
            candidates["status"].astype(str).str.upper().isin(FINAL_STATUSES)
            & pd.to_numeric(candidates["home_score"], errors="coerce").notna()
            & pd.to_numeric(candidates["away_score"], errors="coerce").notna()
        ]
        if final_candidates.empty:
            counters["still_running"] += 1
            continue

        result = final_candidates.sort_values("distance").iloc[0]
        home_score = int(float(result["home_score"]))
        away_score = int(float(result["away_score"]))
        actual_outcome = result_outcome(home_score, away_score)
        selected_outcome = str(row.get("selected_outcome"))
        won = selected_outcome == actual_outcome
        odds = _number(row.get("selected_odds"), 1.0)
        stake = _number(row.get("stake_eur"), 1.0)
        profit_units = odds - 1.0 if won else -1.0

        values = {
            "result_status": "won" if won else "lost",
            "actual_result": {"home_win": "w", "draw": "d", "away_win": "l"}[actual_outcome],
            "actual_outcome": actual_outcome,
            "actual_home_score": home_score,
            "actual_away_score": away_score,
            "match_found": True,
            "won_live_bet": won,
            "realized_profit_units": profit_units,
            "realized_profit": profit_units * stake,
        }
        for column, value in values.items():
            if column not in updated.columns:
                updated[column] = pd.NA
            updated.at[index, column] = value
        counters["settled"] += 1

    return updated, counters


def active_recommended_rows(ledger: pd.DataFrame, portfolio_name: str) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    recommended = ledger.get("recommended", pd.Series(False, index=ledger.index)).map(_truthy)
    portfolio = ledger.get("portfolio_name", pd.Series("", index=ledger.index)).astype(str)
    return ledger.loc[recommended & (portfolio == portfolio_name)].copy()


def update_public_snapshot(
    snapshot: dict[str, Any],
    ledger: pd.DataFrame,
    *,
    portfolio_name: str,
    generated_at: datetime,
) -> dict[str, Any]:
    """Patch the deployed read model without rerunning models or changing recommendations."""
    output = json.loads(json.dumps(snapshot))
    active = active_recommended_rows(ledger, portfolio_name)

    def row_key(date: object, home: object, away: object) -> tuple[str, str, str]:
        return (
            str(date)[:10],
            normalize_team_name(home),
            normalize_team_name(away),
        )

    ledger_by_match = {
        row_key(row.get("date"), row.get("team_name"), row.get("opponent_name")): row
        for row in active.to_dict(orient="records")
    }

    activity = output.setdefault("activity", [])
    activity_keys: set[tuple[str, str, str]] = set()
    for item in activity:
        key = row_key(item.get("date"), item.get("homeTeam"), item.get("awayTeam"))
        activity_keys.add(key)
        row = ledger_by_match.get(key)
        if row is None:
            continue
        status = str(row.get("result_status") or "pending")
        item["status"] = status
        item["profitUnits"] = _number(row.get("realized_profit_units"))
        if status in TERMINAL_RESULT_STATUSES and pd.notna(row.get("actual_home_score")):
            item["actualScore"] = f"{int(float(row['actual_home_score']))} - {int(float(row['actual_away_score']))}"

    for key, row in ledger_by_match.items():
        if key in activity_keys:
            continue
        identity = str(row.get("snapshot_key") or "|").encode("utf-8")
        status = str(row.get("result_status") or "pending")
        activity.append(
            {
                "id": hashlib.sha1(identity).hexdigest()[:12],
                "date": str(row.get("date")),
                "league": row.get("league", ""),
                "leagueLabel": LEAGUE_LABELS.get(str(row.get("league")), str(row.get("league", ""))),
                "homeTeam": row.get("team_name", ""),
                "awayTeam": row.get("opponent_name", ""),
                "outcomeLabel": OUTCOME_LABELS.get(str(row.get("selected_outcome")), "Choix publié"),
                "portfolioLabel": "Stratégie championne",
                "odds": _number(row.get("selected_odds")),
                "status": status,
                "actualScore": (
                    f"{int(float(row['actual_home_score']))} - {int(float(row['actual_away_score']))}"
                    if status in TERMINAL_RESULT_STATUSES and pd.notna(row.get("actual_home_score"))
                    else None
                ),
                "recommended": True,
                "profitUnits": _number(row.get("realized_profit_units")),
            }
        )

    final_keys = {
        key
        for key, row in ledger_by_match.items()
        if str(row.get("result_status") or "pending") in TERMINAL_RESULT_STATUSES
    }
    output["predictions"] = [
        prediction
        for prediction in output.get("predictions", [])
        if row_key(prediction.get("date"), prediction.get("homeTeam"), prediction.get("awayTeam")) not in final_keys
    ]

    statuses = active.get("result_status", pd.Series("pending", index=active.index)).fillna("pending").astype(str)
    won = int((statuses == "won").sum())
    lost = int((statuses == "lost").sum())
    void = int((statuses == "void").sum())
    settled = won + lost
    pending = int((~statuses.isin(TERMINAL_RESULT_STATUSES)).sum())
    profit_values = (
        active["realized_profit_units"]
        if "realized_profit_units" in active.columns
        else pd.Series(0.0, index=active.index)
    )
    profit_units = float(pd.to_numeric(profit_values, errors="coerce").fillna(0).sum())
    roi = profit_units / settled if settled else None
    hit_rate = won / settled if settled else None

    summary = output.setdefault("summary", {})
    summary.update(
        {
            "upcomingBets": len(output["predictions"]),
            "currentRecommendations": len(output["predictions"]),
            "settledLiveBets": settled,
            "pendingPredictions": pending,
            "wonPredictions": won,
            "lostPredictions": lost,
            "liveProfitUnits": profit_units,
            "liveRoi": roi,
        }
    )
    tracking = output.setdefault("tracking", {})
    tracking.update(
        {
            "pending": pending,
            "verified": settled,
            "won": won,
            "lost": lost,
            "void": void,
            "hitRate": hit_rate,
            "lastSyncAt": generated_at.isoformat(),
        }
    )
    performance_live = output.setdefault("performance", {}).setdefault("live", {})
    performance_live.update(
        {
            "settledBets": settled,
            "wonBets": won,
            "profitUnits": profit_units,
            "roi": roi,
            "asOf": generated_at.date().isoformat(),
        }
    )
    output.setdefault("meta", {})["generatedAt"] = generated_at.isoformat()
    return output


def collect_results_for_due_rows(
    ledger: pd.DataFrame,
    *,
    now: pd.Timestamp,
    minimum_elapsed_minutes: int,
    portfolio_name: str,
    timeout_seconds: float,
) -> tuple[pd.DataFrame, list[str]]:
    due = ledger.loc[
        due_prediction_mask(
            ledger,
            now=now,
            minimum_elapsed_minutes=minimum_elapsed_minutes,
            portfolio_name=portfolio_name,
        )
    ].copy()
    if due.empty:
        return pd.DataFrame(), []

    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    groups = {
        (str(row.league), infer_season(paris_datetime(row.date)))
        for row in due.itertuples(index=False)
    }
    for league, season in sorted(groups):
        try:
            sportsdb = fetch_sportsdb_fixture_times(league, season, timeout_seconds=timeout_seconds)
            if not sportsdb.empty:
                sportsdb = sportsdb.copy()
                sportsdb["result_source"] = "thesportsdb_final_status"
                frames.append(sportsdb)
        except Exception as exc:
            warnings.append(f"TheSportsDB {league}: {exc}")
        try:
            understat = understat_finished_results(
                get_league_data(league, str(season)),
                league=league,
            )
            if not understat.empty:
                frames.append(understat)
        except Exception as exc:
            warnings.append(f"Understat {league}: {exc}")

    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérifie rapidement les résultats des paris terminés.")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--status-output", required=True)
    parser.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_NAME)
    parser.add_argument("--minimum-elapsed-minutes", type=int, default=105)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--as-of", default="")
    args = parser.parse_args()

    ledger_path = Path(args.ledger).resolve()
    snapshot_path = Path(args.snapshot).resolve()
    status_path = Path(args.status_output).resolve()
    ledger = pd.read_csv(ledger_path)
    now = (
        paris_datetime(args.as_of)
        if args.as_of
        else pd.Timestamp.now(tz=DISPLAY_TIMEZONE).tz_localize(None)
    )
    results, warnings = collect_results_for_due_rows(
        ledger,
        now=now,
        minimum_elapsed_minutes=args.minimum_elapsed_minutes,
        portfolio_name=args.portfolio,
        timeout_seconds=args.timeout_seconds,
    )
    updated, counters = settle_due_predictions(
        ledger,
        results,
        now=now,
        minimum_elapsed_minutes=args.minimum_elapsed_minutes,
        portfolio_name=args.portfolio,
    )

    changed = counters["settled"] > 0
    if changed:
        updated.to_csv(ledger_path, index=False)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        patched = update_public_snapshot(
            snapshot,
            updated,
            portfolio_name=args.portfolio,
            generated_at=datetime.now(timezone.utc),
        )
        snapshot_path.write_text(json.dumps(patched, ensure_ascii=False, indent=2), encoding="utf-8")

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "changed": changed,
        **counters,
        "checkedAtParis": now.isoformat(),
        "warnings": warnings,
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(status)


if __name__ == "__main__":
    main()
