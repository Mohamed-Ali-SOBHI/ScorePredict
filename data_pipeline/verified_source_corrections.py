"""Narrow, documented source metadata corrections; never infer venue by odds."""
from copy import deepcopy


VENUE_CORRECTIONS = [{
    "league": "Ligue_1", "season": 2026, "fixture_id": "31948",
    "date": "2026-08-23 18:45:00", "home_id": "163", "away_id": "161",
    "reason": "Rennes hosted Paris at Roazhon Park; Understat reversed the venue.",
    "evidence": [
        "https://www.psg.fr/content/les-resultats-de-la-1re-journee-de-ligue-1-stade-rennais-paris-saint-journee-ligue-1-2026-2027",
        "https://www.psg.fr/matchs/football-masculin/20262027/paris-vs-rennes-2026-08-23",
    ],
}]


def correct_verified_venues(payload, league, season):
    """Preserve each club's own statistics; only correct the verified venue.

    The untouched payload is saved by the caller for audit. Match identifiers,
    dates and club ids must all agree with the rule. Already corrected source
    data is left as-is; unexpected changes fail rather than being overwritten.
    """
    rules = [r for r in VENUE_CORRECTIONS if r["league"] == league and r["season"] == int(season)]
    if not rules:
        return payload, []
    result, applied = deepcopy(payload), []
    fixtures = result.get("dates") or []
    fixtures = list(fixtures.values()) if isinstance(fixtures, dict) else fixtures
    raw_teams = result.get("teams") or {}
    entries = raw_teams.items() if isinstance(raw_teams, dict) else ((None, t) for t in raw_teams)
    teams = {str(t.get("id") or t.get("team_id") or key): t for key, t in entries}
    for rule in rules:
        matches = [f for f in fixtures if str(f.get("id")) == rule["fixture_id"]]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("Duplicate fixture for verified venue correction")
        fixture = matches[0]
        home, away = rule["home_id"], rule["away_id"]
        actual_ids = (str(fixture["h"]["id"]), str(fixture["a"]["id"]))
        if fixture.get("datetime") != rule["date"] or set(actual_ids) != {home, away}:
            raise ValueError("Verified venue correction no longer matches source identity/date")
        changed = False
        if actual_ids == (away, home):
            fixture["h"], fixture["a"] = fixture["a"], fixture["h"]
            for field in ("goals", "xG"):
                if isinstance(fixture.get(field), dict):
                    fixture[field]["h"], fixture[field]["a"] = fixture[field].get("a"), fixture[field].get("h")
            forecast = fixture.get("forecast")
            if isinstance(forecast, dict) and "w" in forecast and "l" in forecast:
                forecast["w"], forecast["l"] = forecast["l"], forecast["w"]
            changed = True
        for tid, side in ((home, "h"), (away, "a")):
            history = [h for h in teams.get(tid, {}).get("history", []) if h.get("date") == rule["date"]]
            if fixture.get("isResult") is True and len(history) != 1:
                raise ValueError("Verified venue correction requires both team observations")
            for row in history:
                if row.get("h_a") not in {"h", "a"}:
                    raise ValueError("Invalid venue in source history")
                if row["h_a"] != side:
                    row["h_a"] = side
                    changed = True
        if changed:
            applied.append(dict(rule))
    return result, applied
