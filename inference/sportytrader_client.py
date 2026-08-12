from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pandas as pd


SPORTYTRADER_LEAGUE_CONFIGS = {
    "EPL": {
        "url": "https://www.sportytrader.com/en/odds/football/england/premier-league-49/",
        "title_contains": "Premier League",
        "section_title": "Upcoming Premier League matches",
    },
    "Bundesliga": {
        "url": "https://www.sportytrader.com/en/odds/football/germany/bundesliga-65/",
        "title_contains": "Bundesliga",
        "section_title": "Upcoming Bundesliga matches",
    },
    "Serie_A": {
        "url": "https://www.sportytrader.com/en/odds/football/italy/serie-a-79/",
        "title_contains": "Serie A",
        "section_title": "Upcoming Serie A matches",
    },
    "Ligue_1": {
        "url": "https://www.sportytrader.com/en/odds/football/france/ligue-1-123/",
        "title_contains": "Ligue 1",
        "section_title": "Upcoming Ligue 1 matches",
    },
    "La_liga": {
        "url": "https://www.sportytrader.com/en/odds/football/spain/laliga-108/",
        "title_contains": "LaLiga",
        "section_title": "Upcoming LaLiga matches",
    },
}
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
NODE_EXECUTABLE = shutil.which("node") or "node"
PAGE_READER = SCRIPT_DIR / "sportytrader_page_text.mjs"
DATE_LINE_RE = re.compile(r"^\d{1,2}\s+[A-Z][a-z]{2}\s+-\s+\d{2}:\d{2}$")
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def fetch_league_page_text(
    league: str,
    *,
    wait_seconds: float,
    timeout_seconds: float,
) -> str:
    if league not in SPORTYTRADER_LEAGUE_CONFIGS:
        raise KeyError(f"Unsupported Sportytrader league: {league}")

    del wait_seconds  # Kept in the public signature for backward compatibility.
    config = SPORTYTRADER_LEAGUE_CONFIGS[league]
    command = [
        NODE_EXECUTABLE,
        str(PAGE_READER),
        "--url",
        config["url"],
        "--section-title",
        config["section_title"],
        "--timeout-ms",
        str(max(10000, int(timeout_seconds * 1000))),
    ]
    if os.getenv("SCOREPREDICT_BROWSER_HEADLESS", "0").strip().lower() not in {"1", "true", "yes"}:
        command.append("--headed")
    attempts = max(1, int(os.getenv("SCOREPREDICT_BROWSER_ATTEMPTS", "2")))
    failures: list[str] = []
    proc = None
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 15,
            check=False,
        )
        if proc.returncode == 0:
            break
        failures.append(f"tentative {attempt}: {proc.stderr.strip()}")
        if attempt < attempts:
            time.sleep(min(5, attempt * 2))

    if proc is None or proc.returncode != 0:
        raise RuntimeError(
            f"Unable to read Sportytrader for {league} after {attempts} attempt(s).\n"
            + "\n".join(failures)
        )
    import json

    payload = json.loads(proc.stdout)
    title = str(payload.get("title", ""))
    page_text = payload.get("pageText")
    if config["title_contains"] not in title or not isinstance(page_text, str):
        raise ValueError(f"Unexpected Sportytrader response for {league}: {title!r}")
    return page_text


def choose_year(day: int, month: int, date_from: pd.Timestamp) -> int:
    candidates = [date_from.year - 1, date_from.year, date_from.year + 1]
    target = date_from.normalize()
    best_year = date_from.year
    best_distance = None
    for year in candidates:
        try:
            candidate = pd.Timestamp(year=year, month=month, day=day)
        except ValueError:
            continue
        distance = abs((candidate - target).days)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_year = year
    return best_year


def parse_fixture_timestamp(raw: str, date_from: pd.Timestamp) -> pd.Timestamp:
    date_part, time_part = raw.split(" - ", maxsplit=1)
    day_str, month_abbrev = date_part.split()
    month = MONTHS[month_abbrev]
    year = choose_year(int(day_str), month, date_from)
    return pd.Timestamp(f"{year:04d}-{month:02d}-{int(day_str):02d} {time_part}:00")


def parse_upcoming_fixtures(
    page_text: str,
    *,
    date_from: pd.Timestamp,
    date_to: pd.Timestamp,
    league: str,
) -> pd.DataFrame:
    if league not in SPORTYTRADER_LEAGUE_CONFIGS:
        raise KeyError(f"Unsupported Sportytrader league: {league}")

    section_title = SPORTYTRADER_LEAGUE_CONFIGS[league]["section_title"]
    raw_lines = [line.strip().replace("\xa0", " ") for line in page_text.splitlines()]
    lines = [line for line in raw_lines if line]

    try:
        start = lines.index(section_title) + 1
    except ValueError as exc:
        raise ValueError(f"Could not find {section_title!r} section in Sportytrader page text") from exc

    fixtures: list[dict[str, object]] = []
    i = start
    while i + 7 < len(lines):
        if not DATE_LINE_RE.match(lines[i]):
            break
        if " - " not in lines[i + 1]:
            break
        if lines[i + 2] != "1" or lines[i + 4] != "X" or lines[i + 6] != "2":
            break

        home_team, away_team = [part.strip() for part in lines[i + 1].split(" - ", maxsplit=1)]
        fixtures.append(
            {
                "date": parse_fixture_timestamp(lines[i], date_from),
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
                "home_win_odds_open": float(lines[i + 3]),
                "draw_odds_open": float(lines[i + 5]),
                "away_win_odds_open": float(lines[i + 7]),
                "source": "sportytrader_playwright",
            }
        )
        i += 8

    frame = pd.DataFrame(fixtures)
    if frame.empty:
        return frame

    end_of_day = date_to + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return (
        frame[(frame["date"] >= date_from) & (frame["date"] <= end_of_day)]
        .sort_values(["date", "home_team", "away_team"])
        .reset_index(drop=True)
    )


def fetch_upcoming_epl_fixtures(*, date_from: pd.Timestamp, date_to: pd.Timestamp, wait_seconds: float, timeout_seconds: float) -> pd.DataFrame:
    return fetch_upcoming_league_fixtures(
        "EPL",
        date_from=date_from,
        date_to=date_to,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
    )


def fetch_upcoming_league_fixtures(
    league: str,
    *,
    date_from: pd.Timestamp,
    date_to: pd.Timestamp,
    wait_seconds: float,
    timeout_seconds: float,
) -> pd.DataFrame:
    page_text = fetch_league_page_text(
        league,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
    )
    return parse_upcoming_fixtures(
        page_text,
        date_from=date_from,
        date_to=date_to,
        league=league,
    )


def fetch_upcoming_fixtures_for_leagues(
    leagues: list[str],
    *,
    date_from: pd.Timestamp,
    date_to: pd.Timestamp,
    wait_seconds: float,
    timeout_seconds: float,
) -> pd.DataFrame:
    frames = [
        fetch_upcoming_league_fixtures(
            league,
            date_from=date_from,
            date_to=date_to,
            wait_seconds=wait_seconds,
            timeout_seconds=timeout_seconds,
        )
        for league in leagues
    ]
    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "league",
                "home_team",
                "away_team",
                "home_win_odds_open",
                "draw_odds_open",
                "away_win_odds_open",
                "source",
            ]
        )
    return pd.concat(frames, ignore_index=True).sort_values(["date", "league", "home_team"]).reset_index(drop=True)
