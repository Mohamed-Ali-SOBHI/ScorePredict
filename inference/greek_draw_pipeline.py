"""Score the Greek study from the English odds capture and publish first selections only."""
import base64
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from cryptography.fernet import Fernet
from xgboost import Booster, DMatrix

from data_pipeline.http_retry import get
from inference.greek_draw_journal import PORTFOLIO, merge_public_picks
from inference.public_additions import qualifies
from inference.supabase_prediction_store import configuration, request_headers
from train.make_dataset import add_market_implied_features

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "inference/output"
DASHBOARD = ROOT / "production/static/data/dashboard.json"
SITE = "https://mohamed-ali-sobhi.github.io/ScorePredict/data/dashboard.json"
ODDS = "https://www.football-data.co.uk/fixtures.csv"
SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/soccer/gre.1/scoreboard"
RELEASE = ROOT / "inference/releases/greek_draw_2026_27.fernet"
LONDON = ZoneInfo("Europe/London")
LEAD = timedelta(minutes=5)
WINDOW = timedelta(hours=24)
ALIASES = {"aek": "aek athens", "asteras tripolis": "asteras tripoli",
           "levadeiakos": "levadiakos", "olympiakos": "olympiacos"}


def utcnow():
    return datetime.now(timezone.utc)


def odds_capture(now):
    receipts = sorted((p for folder in ("public_additions", "understat_fallback", "english_public")
                       for p in (OUTPUT / folder).glob("capture-*/audit.json")),
                      key=lambda p: p.parent.name, reverse=True)
    for receipt in receipts:
        source = json.loads(receipt.read_text(encoding="utf-8"))["sources"].get("fixtures")
        if not source or source["url"] != ODDS:
            continue
        at = datetime.fromisoformat(source["retrieved_at_utc"])
        if not timedelta(0) <= now - at <= timedelta(minutes=30):
            continue
        raw = gzip.decompress(receipt.with_name("fixtures.gz").read_bytes())
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Invalid odds capture digest")
        return raw, at
    # The English worker can legitimately be skipped on a Greek-only matchday.
    response = get(ODDS, timeout=30)
    response.raise_for_status()
    return response.content, utcnow()


def team(name):
    key = " ".join(name.split()).casefold()
    return ALIASES.get(key, key)


def candidates(raw, now):
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    columns = ("B365H", "B365D", "B365A")
    if not {"Div", "Date", "Time", "HomeTeam", "AwayTeam", *columns} <= set(rows.fieldnames or ()):
        raise ValueError("Incomplete pre-match odds file")
    matches = {}
    ambiguous = set()
    for row in rows:
        if row["Div"] != "G1":
            continue
        try:
            local = datetime.strptime(f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M").replace(tzinfo=LONDON)
            kickoff = local.astimezone(timezone.utc)
            odds = tuple(float(row[c]) for c in columns)
        except (TypeError, ValueError):
            continue
        if not (2026, 7) <= (local.year, local.month) < (2027, 7):
            continue
        if not LEAD <= kickoff - now <= WINDOW or not all(np.isfinite(x) and x > 1 for x in odds):
            continue
        home, away = row["HomeTeam"].strip(), row["AwayTeam"].strip()
        key = (team(home), team(away), kickoff)
        if not home or not away or key[0] == key[1]:
            continue
        if key in matches and matches[key]["prices"] != odds:
            ambiguous.add(key)
        matches[key] = dict(homeTeam=home, awayTeam=away, date=kickoff.isoformat(), prices=odds)
    return {key: row for key, row in matches.items() if key not in ambiguous}


def verify_schedule(matches, events):
    verified = {}
    for event in events:
        for comp in event.get("competitions", []):
            state = (comp.get("status") or event.get("status", {})).get("type", {})
            if state.get("name") != "STATUS_SCHEDULED" or state.get("state") != "pre":
                continue
            sides = {s["homeAway"]: team(s["team"]["displayName"]) for s in comp["competitors"]}
            when = datetime.fromisoformat(comp["date"])
            key = (sides.get("home"), sides.get("away"), when)
            if key in matches and str(event["id"]).isdigit():
                verified.setdefault(key, set()).add("espn:" + str(event["id"]))
    return [dict(matches[key], fixtureId=next(iter(ids))) for key, ids in verified.items() if len(ids) == 1]


def draw_probabilities(rows):
    data = Fernet(os.environ["GREEK_DRAW_KEY_2026_27"].encode()).decrypt(RELEASE.read_bytes())
    models = json.loads(gzip.decompress(data))
    frame = pd.DataFrame([row["prices"] for row in rows], columns=[
        "market_home_win_odds_open", "market_draw_odds_open", "market_away_win_odds_open"])
    frame = add_market_implied_features(frame)
    probabilities = []
    for encoded in models:
        model = Booster(params={"nthread": 2}, model_file=bytearray(base64.b64decode(encoded)))
        probabilities.append(model.predict(DMatrix(frame[model.feature_names], nthread=2)))
    p = np.mean(probabilities, axis=0).astype(float)
    return (p / p.sum(axis=1, keepdims=True))[:, 1]


def selections(rows, probabilities, now):
    picks = []
    for row, p in zip(rows, probabilities, strict=True):
        odds = row["prices"][1]
        if LEAD <= datetime.fromisoformat(row["date"]) - now <= WINDOW and qualifies(p, odds):
            picks.append({k: row[k] for k in ("fixtureId", "homeTeam", "awayTeam", "date")} |
                         dict(odds=odds, modelProbability=float(p), recordedAt=now.isoformat(timespec="milliseconds")))
    return picks


def persist(picks):
    url, secret = configuration()
    if not url or not secret:
        raise ValueError("Missing permanent Greek study ledger")
    endpoint = url + "/rest/v1/prediction_history"
    headers = request_headers(secret)
    records = [dict(snapshot_key=PORTFOLIO + "|" + p["fixtureId"], portfolio_name=PORTFOLIO,
                    fixture_id=p["fixtureId"], league="G1", date=p["date"], kickoff_utc=p["date"],
                    team_name=p["homeTeam"], opponent_name=p["awayTeam"], selected_outcome="draw",
                    selected_odds=p["odds"], predicted_probability=p["modelProbability"],
                    prediction_generated_at_utc=p["recordedAt"], recommended=True) for p in picks]
    if records:
        inserted = requests.post(endpoint, headers={**headers, "Prefer": "resolution=ignore-duplicates"},
                                 params={"on_conflict": "snapshot_key"}, json=records, timeout=30)
        inserted.raise_for_status()
    response = get(endpoint, headers=headers, params={"portfolio_name": "eq." + PORTFOLIO,
                   "select": "fixture_id,kickoff_utc,team_name,opponent_name,selected_odds,predicted_probability,prediction_generated_at_utc",
                   "order": "kickoff_utc.asc", "limit": 1000}, timeout=30)
    response.raise_for_status()
    return [dict(fixtureId=r["fixture_id"], date=r["kickoff_utc"], homeTeam=r["team_name"],
                 awayTeam=r["opponent_name"], odds=r["selected_odds"], modelProbability=r["predicted_probability"],
                 recordedAt=r["prediction_generated_at_utc"]) for r in response.json()]


def main():
    previous = get(SITE, params={"greek_study": utcnow().timestamp()}, timeout=30)
    previous.raise_for_status()
    published = merge_public_picks(previous.json()["greekDrawStudy"])
    held = {p["fixtureId"] for p in published}
    raw, captured = odds_capture(utcnow())
    matches = candidates(raw, captured)
    events = []
    for day in sorted({kickoff.date() for _, _, kickoff in matches}):
        try:
            response = get(SCHEDULE, params={"dates": day.strftime("%Y%m%d")}, timeout=30)
            response.raise_for_status()
            events.extend(response.json()["events"])
        except (requests.RequestException, KeyError, ValueError) as error:
            print(f"::warning::Greek schedule unavailable for {day}: {type(error).__name__}; no new picks for that date.")
    rows = verify_schedule(matches, events)
    probs = draw_probabilities(rows) if rows else []
    now = utcnow()
    if now - captured > timedelta(minutes=30):
        raise ValueError("Greek study odds capture expired")
    chosen = selections(rows, probs, now)
    history = persist(merge_public_picks(published, chosen))
    now = utcnow()
    scheduled = {row["fixtureId"]: datetime.fromisoformat(row["date"]) for row in rows}
    eligible = [p for p in history if p["fixtureId"] not in held
                and scheduled.get(p["fixtureId"]) == datetime.fromisoformat(p["date"])
                and LEAD <= scheduled[p["fixtureId"]] - now <= WINDOW]
    snapshot = json.loads(DASHBOARD.read_text(encoding="utf-8-sig"))
    snapshot["greekDrawStudy"] = merge_public_picks(published, eligible)
    temp = DASHBOARD.with_suffix(".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(DASHBOARD)
    deadline = min((p["date"] for p in eligible), default="")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            print(f"deadline={deadline}", file=output)
    print(f"Greek draws: {len(matches)} priced, {len(rows)} schedule-verified, "
          f"{len(chosen)} selected, {len(eligible)} new, {len(snapshot['greekDrawStudy'])} published records.")


if __name__ == "__main__":
    main()
