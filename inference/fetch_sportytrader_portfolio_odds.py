import argparse
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME, PORTFOLIO_PRESETS
from inference.sportytrader_client import fetch_upcoming_fixtures_for_leagues


DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "sportytrader_upcoming_portfolio_odds.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", required=True, help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_NAME)
    parser.add_argument("--leagues", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument(
        "--allow-partial-leagues",
        action="store_true",
        help="Keep successful leagues when a catalog-only source is temporarily unavailable.",
    )
    return parser.parse_args()


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def get_leagues(args: argparse.Namespace) -> list[str]:
    if args.leagues:
        return [league.strip() for league in args.leagues.split(",") if league.strip()]
    try:
        strategies = PORTFOLIO_PRESETS[args.portfolio]
    except KeyError as exc:
        raise KeyError(f"Unknown portfolio preset: {args.portfolio}") from exc
    leagues = sorted({strategy.bet_league for strategy in strategies})
    return leagues


def main() -> None:
    args = parse_args()
    date_from = pd.Timestamp(args.date_from)
    date_to = pd.Timestamp(args.date_to)
    if date_to < date_from:
        raise ValueError("--date-to must be >= --date-from")

    leagues = get_leagues(args)
    fixtures = fetch_upcoming_fixtures_for_leagues(
        leagues,
        date_from=date_from,
        date_to=date_to,
        wait_seconds=args.wait_seconds,
        timeout_seconds=args.timeout_seconds,
        allow_partial=args.allow_partial_leagues,
    )

    output_path = resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fixtures.to_csv(output_path, index=False)

    print(
        {
            "portfolio": args.portfolio,
            "leagues": leagues,
            "fixtures_found": int(len(fixtures)),
            "date_from": date_from.strftime("%Y-%m-%d"),
            "date_to": date_to.strftime("%Y-%m-%d"),
            "output": str(output_path),
        }
    )
    if not fixtures.empty:
        league_counts = fixtures["league"].value_counts().sort_index().to_dict()
        print({"fixtures_by_league": {league: int(count) for league, count in league_counts.items()}})
        print(fixtures.to_string(index=False))


if __name__ == "__main__":
    main()
