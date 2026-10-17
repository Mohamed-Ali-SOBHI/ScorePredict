"""Daily scoreboards; no model inputs or betting decisions are changed here."""
from __future__ import annotations

import gzip
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from data_pipeline.market_data import normalize_team_name

LEAGUES = {"EPL": "eng.1", "La_liga": "esp.1", "Bundesliga": "ger.1", "Serie_A": "ita.1", "Ligue_1": "fra.1"}
# Explicit provider spellings, checked against the current club registry.
# Keep these local to results: changing model feature identities is unnecessary.
ALIASES = {
    "afc bournemouth": "bournemouth", "brighton and hove albion": "brighton",
    "leeds united": "leeds", "tottenham hotspur": "tottenham",
    "1 fc union berlin": "union berlin", "borussia monchengladbach": "borussia m gladbach",
    "fc augsburg": "augsburg", "hamburg sv": "hamburger sv", "sc freiburg": "freiburg",
    "tsg hoffenheim": "hoffenheim", "as roma": "roma", "internazionale": "inter",
    "aj auxerre": "auxerre", "as monaco": "monaco", "le havre ac": "le havre",
    "stade rennais": "rennes",
}
COLUMNS = ["league", "home_team_norm", "away_team_norm", "official_date", "status",
           "home_score", "away_score", "result_source", "result_event_id"]


def team_name(name: object) -> str:
    normalized = normalize_team_name(name)
    return ALIASES.get(normalized, normalized)


def score(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isascii() and text.isdigit() else None


def parse_scoreboard(payload: dict, *, league: str, day: str) -> pd.DataFrame:
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("ESPN scoreboard has no events list")
    rows = []
    for event in payload["events"]:
        for competition in event.get("competitions", []):
            sides = {c.get("homeAway"): c for c in competition.get("competitors", [])}
            if set(sides) != {"home", "away"} or len(competition.get("competitors", [])) != 2:
                continue
            date = pd.to_datetime(competition.get("date") or event.get("date"), errors="coerce", utc=True)
            if pd.isna(date) or date.tz_convert("Europe/Paris").date().isoformat() != day:
                continue
            home, away = sides["home"], sides["away"]
            home_name = team_name(home.get("team", {}).get("displayName", ""))
            away_name = team_name(away.get("team", {}).get("displayName", ""))
            if not home_name or not away_name or home_name == away_name:
                continue
            state = (competition.get("status") or event.get("status") or {}).get("type", {})
            # Only regular-time league finals: not abandoned, awarded, extra
            # time or shoot-outs, even if those carry completed=true.
            final = (state.get("completed") is True and state.get("state") == "post"
                     and state.get("name") == "STATUS_FULL_TIME")
            home_score, away_score = score(home.get("score")), score(away.get("score"))
            rows.append({
                "league": league, "home_team_norm": home_name, "away_team_norm": away_name,
                "official_date": date.tz_convert("Europe/Paris").tz_localize(None),
                "status": "FT" if final and home_score is not None and away_score is not None else "UNCONFIRMED",
                "home_score": home_score, "away_score": away_score,
                "result_source": "espn_scoreboard", "result_event_id": str(event.get("id", "")),
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_scoreboard(league: str, day: str, *, timeout_seconds: float = 20) -> pd.DataFrame:
    date = pd.Timestamp(day).strftime("%Y%m%d")
    query = urlencode({"dates": date, "limit": 100})
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUES[league]}/scoreboard?{query}"
    request = Request(url, headers={"User-Agent": "ScorePredict/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
    return parse_scoreboard(json.loads(body), league=league, day=day)
