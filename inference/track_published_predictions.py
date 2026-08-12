from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from inference.live_tracking import append_tracking_rows, build_tracking_rows


OUTCOMES = ("home_win", "draw", "away_win")


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {
        "",
        "0",
        "0.0",
        "false",
        "no",
        "none",
        "nan",
        "<na>",
    }


def published_rows(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.Series] = []
    fixture_columns = ["date", "league", "team_name", "opponent_name"]
    for _, fixture in scored.groupby(fixture_columns, sort=True, dropna=False):
        recommended = fixture[fixture["recommended_bet"].map(as_bool)] if "recommended_bet" in fixture else fixture.iloc[0:0]
        row = recommended.iloc[0].copy() if not recommended.empty else fixture.iloc[0].copy()

        is_recommended = not recommended.empty
        if not is_recommended:
            probabilities = {
                "home_win": float(row.get("pred_home_win", 0.0)),
                "draw": float(row.get("pred_draw", 0.0)),
                "away_win": float(row.get("pred_away_win", 0.0)),
            }
            outcome = max(probabilities, key=probabilities.get)
            row["selected_outcome"] = outcome
            row["predicted_probability"] = probabilities[outcome]
            row["selected_odds"] = row.get(f"market_{outcome}_odds_open", row.get("selected_odds"))
            row["edge"] = 0.0
            row["stake_eur"] = 0.0

        row["recommended_bet"] = is_recommended
        row["strategy_names"] = row.get("strategy_names") or row.get("strategy_name") or ""
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mémorise exactement les prévisions affichées sur le site.")
    parser.add_argument("--predictions", default="inference/output/upcoming_portfolio_predictions.csv")
    parser.add_argument("--ledger", default="inference/output/live_portfolio_bet_log.csv")
    parser.add_argument("--portfolio", default="published_dashboard")
    args = parser.parse_args()

    source = Path(args.predictions).resolve()
    ledger = Path(args.ledger).resolve()
    scored = pd.read_csv(source)
    selected = published_rows(scored)
    tracked = build_tracking_rows(selected, portfolio_name=args.portfolio)
    append_tracking_rows(tracked, ledger)
    print({"published_predictions": len(tracked), "ledger": str(ledger)})


if __name__ == "__main__":
    main()
