"""Prospective, private Venn–Abers decisions against the published ticket ledger."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import requests

from inference.publication_policy import public_row
from inference.supabase_prediction_store import configuration, request_headers

PORTFOLIO = "private_venn_abers_2026_11_23"
CALIBRATION = Path(__file__).with_name("venn_calibration_2025.json")
REPORT = Path("inference/output/venn_observation/report.json")
SITE = "https://mohamed-ali-sobhi.github.io/ScorePredict/data/dashboard.json"
TERMINAL = {"won", "lost", "void"}


def lower_probability(samples, probability):
    """Isotonic regression at the test point, augmented with its hypothetical loss."""
    groups = {}
    for score, win in [*samples, (probability, 0)]:
        wins, size = groups.get(score, (0, 0))
        groups[score] = (wins + win, size + 1)
    blocks = []
    for end, (wins, size) in sorted(groups.items()):
        while blocks and blocks[-1][1] * size > wins * blocks[-1][2]:
            _, left_wins, left_size = blocks.pop()
            wins += left_wins
            size += left_size
        blocks.append((end, wins, size))
    return next(wins / size for end, wins, size in blocks if end >= probability)


def decision(row, calibration, now):
    if row.get("recommended") is not True or row.get("historicalOnly") or not public_row(row):
        return None
    if row.get("status") != "pending":
        return None
    kickoff = datetime.fromisoformat(row["date"])
    published = datetime.fromisoformat(row["recordedAt"])
    # Limit use of 2025/26 calibration to its registered test season.
    if not published <= now < kickoff or not (2026, 8) <= (kickoff.year, kickoff.month) < (2027, 7):
        return None
    p, price = float(row["modelProbability"]), float(row["odds"])
    if not 0 <= p <= 1 or not math.isfinite(price) or price <= 1:
        raise ValueError("Invalid published probability or odds")
    lower = lower_probability(calibration[row["outcome"]], p)
    selected = lower * price * .98 > 1
    return dict(snapshot_key=PORTFOLIO + "|" + row["id"], portfolio_name=PORTFOLIO,
                prediction_generated_at_utc=now.isoformat(), date=row["date"], kickoff_utc=row["date"],
                league=row["league"], team_name=row["homeTeam"], opponent_name=row["awayTeam"],
                selected_outcome=row["outcome"], selected_odds=price, predicted_probability=lower,
                raw_model_probability=p, strategy_names=row["strategy"], recommended=False,
                stake_eur=0, result_status="pending",
                probability_note=json.dumps(dict(selected=selected, publishedAt=row["recordedAt"])))


def private_report(rows, now):
    tickets = []
    for row in rows:
        selected = json.loads(row["probability_note"])["selected"]
        status = row["result_status"]
        tickets.append(dict(date=row["date"], home=row["team_name"], away=row["opponent_name"],
                            capturedAt=row["prediction_generated_at_utc"], selected=selected,
                            status=status, odds=row["selected_odds"], lower=row["predicted_probability"]))
    def metrics(group):
        settled = [r for r in group if r["status"] in {"won", "lost"}]
        gain = round(sum(r["odds"] - 1 if r["status"] == "won" else -1 for r in settled), 8)
        return dict(settled=len(settled), profit=gain, roi=gain / len(settled) if settled else None,
                    pending=sum(r["status"] not in TERMINAL for r in group))
    return dict(schemaVersion=1, private=True, portfolio=PORTFOLIO, updatedAt=now.isoformat(),
                reference=metrics(tickets), filtered=metrics([r for r in tickets if r["selected"]]),
                tickets=tickets)


def main():
    url, key = configuration()
    if not url or not key:
        raise ValueError("Private store unavailable")
    endpoint = url + "/rest/v1/prediction_history"
    headers = request_headers(key)
    scope = {"portfolio_name": "eq." + PORTFOLIO}
    def read():
        result = requests.get(endpoint, params={**scope, "order": "date.asc"}, headers=headers, timeout=30)
        result.raise_for_status()
        return result.json()
    response = requests.get(SITE, params={"observation": datetime.now(timezone.utc).timestamp()}, timeout=30)
    response.raise_for_status()
    activity = response.json()["activity"]
    now = datetime.now(timezone.utc)
    calibration = json.loads(CALIBRATION.read_text(encoding="utf8"))
    journal = {r["snapshot_key"]: r for r in read()}
    for row in activity:
        identity = PORTFOLIO + "|" + row["id"]
        if identity not in journal:
            entry = decision(row, calibration, now)
            if entry:
                # The first capture wins, including abstentions. Replays cannot change it.
                result = requests.post(endpoint, params={"on_conflict": "snapshot_key"}, json=entry,
                                       headers={**headers, "Prefer": "resolution=ignore-duplicates"}, timeout=30)
                result.raise_for_status()
            continue
        receipt = journal[identity]
        if receipt["result_status"] != "pending" or row.get("status") not in TERMINAL:
            continue
        status = row["status"]
        selected = json.loads(receipt["probability_note"])["selected"]
        profit = receipt["selected_odds"] - 1 if status == "won" else -1 if status == "lost" else 0
        result = requests.patch(endpoint, headers=headers,
                                params={**scope, "snapshot_key": "eq." + identity, "result_status": "eq.pending"},
                                json={"result_status": status, "realized_profit_units": profit if selected else 0},
                                timeout=30)
        result.raise_for_status()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(private_report(read(), now), allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
