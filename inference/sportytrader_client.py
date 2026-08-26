from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from data_pipeline.market_data import normalize_team_name


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
DISPLAY_TIMEZONE = "Europe/Paris"
THE_SPORTS_DB_LEAGUE_IDS = {
    "EPL": "4328",
    "Bundesliga": "4331",
    "Serie_A": "4332",
    "Ligue_1": "4334",
    "La_liga": "4335",
}


class KickoffTimeVerificationError(ValueError):
    """Raised when a league cannot independently verify SportyTrader's time offset."""


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


def infer_season(date_value: pd.Timestamp) -> int:
    value = pd.Timestamp(date_value)
    return value.year if value.month >= 7 else value.year - 1


def parse_sportsdb_fixture_times(payload: dict, *, league: str) -> pd.DataFrame:
    """Convert TheSportsDB's UTC schedule and scores to Europe/Paris times."""
    fixtures = payload.get("events") or []

    rows: list[dict[str, object]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        raw_date = fixture.get("strTimestamp")
        home_name = str(fixture.get("strHomeTeam") or "").strip()
        away_name = str(fixture.get("strAwayTeam") or "").strip()
        if not raw_date or not home_name or not away_name:
            continue
        date = pd.to_datetime(raw_date, errors="coerce", utc=True)
        if pd.isna(date):
            continue
        rows.append(
            {
                "league": league,
                "home_team_norm": normalize_team_name(home_name),
                "away_team_norm": normalize_team_name(away_name),
                "official_date": date.tz_convert(DISPLAY_TIMEZONE).tz_localize(None),
                "status": str(fixture.get("strStatus") or "").strip().upper(),
                "home_score": pd.to_numeric(fixture.get("intHomeScore"), errors="coerce"),
                "away_score": pd.to_numeric(fixture.get("intAwayScore"), errors="coerce"),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "league",
            "home_team_norm",
            "away_team_norm",
            "official_date",
            "status",
            "home_score",
            "away_score",
        ],
    )


def fetch_sportsdb_fixture_times(
    league: str,
    season: int,
    *,
    timeout_seconds: float,
) -> pd.DataFrame:
    try:
        league_id = THE_SPORTS_DB_LEAGUE_IDS[league]
    except KeyError as exc:
        raise KeyError(f"Unsupported TheSportsDB league: {league}") from exc

    attempts = max(1, int(os.getenv("SCOREPREDICT_SCHEDULE_ATTEMPTS", "3")))
    failures: list[str] = []
    season_label = f"{season}-{season + 1}"
    query = urlencode({"id": league_id, "s": season_label})
    api_key = os.getenv("THESPORTSDB_API_KEY", "123").strip() or "123"
    url = f"https://www.thesportsdb.com/api/v1/json/{api_key}/eventsseason.php?{query}"
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
            payload = json.loads(body.decode("utf-8"))
            return parse_sportsdb_fixture_times(payload, league=league)
        except Exception as exc:
            failures.append(f"tentative {attempt}: {exc}")
            if attempt < attempts:
                time.sleep(min(5, attempt * 2))
    raise RuntimeError(
        f"Unable to read reliable fixture times from TheSportsDB for {league} {season} "
        f"after {attempts} attempt(s): {'; '.join(failures)}"
    )


def reconcile_fixture_times(
    fixtures: pd.DataFrame,
    official: pd.DataFrame,
    *,
    fallback_offset_minutes: int | None = None,
) -> pd.DataFrame:
    """Correct SportyTrader's server-local hours using a verified league offset."""
    if fixtures.empty:
        return fixtures.copy()

    source = fixtures.copy()
    source["home_team_norm"] = source["home_team"].map(normalize_team_name)
    source["away_team_norm"] = source["away_team"].map(normalize_team_name)
    official_rows = official.copy()
    offsets_by_league: dict[str, pd.Timedelta] = {}
    fallback_leagues: set[str] = set()

    for league, league_fixtures in source.groupby("league"):
        offsets: list[pd.Timedelta] = []
        for fixture in league_fixtures.itertuples(index=False):
            candidates = official_rows[
                (official_rows["league"] == fixture.league)
                & (official_rows["home_team_norm"] == fixture.home_team_norm)
                & (official_rows["away_team_norm"] == fixture.away_team_norm)
            ].copy()
            if candidates.empty:
                continue
            candidates["distance"] = (
                pd.to_datetime(candidates["official_date"]) - pd.Timestamp(fixture.date)
            ).abs()
            candidates = candidates[candidates["distance"] <= pd.Timedelta(days=2)]
            if candidates.empty:
                continue
            official_date = pd.Timestamp(candidates.sort_values("distance").iloc[0]["official_date"])
            offsets.append(official_date - pd.Timestamp(fixture.date))

        if not offsets:
            if fallback_offset_minutes is None:
                raise KickoffTimeVerificationError(
                    f"Unable to verify the Europe/Paris kickoff-time offset for {league}."
                )
            offsets_by_league[str(league)] = pd.Timedelta(minutes=fallback_offset_minutes)
            fallback_leagues.add(str(league))
            continue
        rounded_minutes = pd.Series(
            [round(offset.total_seconds() / 60) for offset in offsets],
            dtype="int64",
        )
        mode = rounded_minutes.mode()
        if mode.empty:
            raise KickoffTimeVerificationError(
                f"Unable to determine a stable kickoff-time offset for {league}."
            )
        offset_minutes = int(mode.iloc[0])
        agreement = int((rounded_minutes == offset_minutes).sum())
        if agreement * 2 < len(rounded_minutes):
            raise KickoffTimeVerificationError(
                f"Official kickoff times disagree for {league}; refusing to publish uncertain hours."
            )
        offsets_by_league[str(league)] = pd.Timedelta(minutes=offset_minutes)

    source["date"] = pd.to_datetime(source["date"]) + source["league"].map(offsets_by_league)
    source["source"] = source.apply(
        lambda row: str(row["source"])
        + (
            "+shared_verified_timezone"
            if str(row["league"]) in fallback_leagues
            else "+sportsdb_timezone"
        ),
        axis=1,
    )
    result = source.drop(columns=["home_team_norm", "away_team_norm"])
    result.attrs["verified_offset_minutes_by_league"] = {
        league: int(offset.total_seconds() // 60)
        for league, offset in offsets_by_league.items()
    }
    result.attrs["fallback_leagues"] = sorted(fallback_leagues)
    return result


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
    fallback_offset_minutes: int | None = None,
    _source_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] | None = None,
) -> pd.DataFrame:
    cached = _source_cache.get(league) if _source_cache is not None else None
    if cached is not None:
        fixtures, official = cached
    else:
        page_text = fetch_league_page_text(
            league,
            wait_seconds=wait_seconds,
            timeout_seconds=timeout_seconds,
        )
        verification_date_to = max(date_to, date_from + pd.Timedelta(days=60))
        fixtures = parse_upcoming_fixtures(
            page_text,
            date_from=date_from,
            date_to=verification_date_to,
            league=league,
        )
        if fixtures.empty:
            return fixtures

        seasons = {infer_season(date_from), infer_season(date_to)}
        official = pd.concat(
            [
                fetch_sportsdb_fixture_times(
                    league,
                    season,
                    timeout_seconds=timeout_seconds,
                )
                for season in sorted(seasons)
            ],
            ignore_index=True,
        )
        if _source_cache is not None:
            _source_cache[league] = (fixtures, official)
    corrected = reconcile_fixture_times(
        fixtures,
        official,
        fallback_offset_minutes=fallback_offset_minutes,
    )
    correction_metadata = dict(corrected.attrs)
    end_of_day = date_to + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    result = corrected[
        (corrected["date"] >= date_from) & (corrected["date"] <= end_of_day)
    ].reset_index(drop=True)
    result.attrs.update(correction_metadata)
    return result


def _shared_verified_offset(offsets: list[int]) -> int | None:
    if not offsets:
        return None
    values = pd.Series(offsets, dtype="int64")
    counts = values.value_counts()
    selected = int(counts.index[0])
    agreement = int(counts.iloc[0])
    if agreement < 2 or agreement * 2 <= len(values):
        return None
    return selected


def fetch_upcoming_fixtures_for_leagues(
    leagues: list[str],
    *,
    date_from: pd.Timestamp,
    date_to: pd.Timestamp,
    wait_seconds: float,
    timeout_seconds: float,
    allow_partial: bool = False,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    deferred: list[tuple[str, KickoffTimeVerificationError]] = []
    unavailable: list[tuple[str, RuntimeError]] = []
    verified_offsets: list[int] = []
    source_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}

    for league in leagues:
        try:
            frame = fetch_upcoming_league_fixtures(
                league,
                date_from=date_from,
                date_to=date_to,
                wait_seconds=wait_seconds,
                timeout_seconds=timeout_seconds,
                _source_cache=source_cache,
            )
        except KickoffTimeVerificationError as exc:
            deferred.append((league, exc))
            continue
        except RuntimeError as exc:
            if not allow_partial:
                raise
            unavailable.append((league, exc))
            print(f"Skipping unavailable league {league}: {exc}")
            continue
        frames.append(frame)
        offset = frame.attrs.get("verified_offset_minutes_by_league", {}).get(league)
        if offset is not None:
            verified_offsets.append(int(offset))

    if deferred:
        print({"verified_kickoff_offsets_minutes": verified_offsets})
        shared_offset = _shared_verified_offset(verified_offsets)
        if shared_offset is None:
            if not allow_partial:
                raise deferred[0][1]
            for league, exc in deferred:
                print(f"Skipping league with unverified kickoff times {league}: {exc}")
        else:
            for league, _ in deferred:
                print(
                    f"Using the {shared_offset:+d}-minute offset verified on the other "
                    f"SportyTrader league pages for {league}."
                )
                frames.append(
                    fetch_upcoming_league_fixtures(
                        league,
                        date_from=date_from,
                        date_to=date_to,
                        wait_seconds=wait_seconds,
                        timeout_seconds=timeout_seconds,
                        fallback_offset_minutes=shared_offset,
                        _source_cache=source_cache,
                    )
                )
    if not frames:
        if unavailable or deferred:
            failures = [f"{league}: {exc}" for league, exc in [*unavailable, *deferred]]
            raise RuntimeError("No league fixture source succeeded: " + "; ".join(failures))
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
