"""Public projection of the prospective Greek draw study, independent of live betting totals."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

from inference.public_additions import qualifies
from inference.best_prices import qualifies_ticket

SEED = Path(__file__).with_name("greek_draw_picks.json")
PORTFOLIO = "study_greek_draw_price_2026_27"
FIELDS = ("fixtureId", "date", "homeTeam", "awayTeam", "odds", "modelProbability", "recordedAt")


def merge_public_picks(*groups):
    journal = {}
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rows in (seed, *groups):
        for pick in rows:
            if "fixtureId" not in pick:
                # Earlier public snapshots used the kickoff and the club names as the identity.
                if any(pick["homeTeam"] == p["homeTeam"] and pick["awayTeam"] == p["awayTeam"]
                       and datetime.fromisoformat(pick["date"]) == datetime.fromisoformat(p["date"])
                       for p in seed):
                    continue
                raise ValueError("Unidentified Greek study fixture")
            row = {k: pick[k] for k in FIELDS}
            if "publishedQuote" in pick:
                q = pick["publishedQuote"]
                if (q["odds"] != row["odds"] or not qualifies(row["modelProbability"], q["referenceOdds"])
                        or datetime.fromisoformat(q["checkedAt"]) > datetime.fromisoformat(row["recordedAt"]) + timedelta(milliseconds=1)):
                    raise ValueError("Invalid Greek study offer")
                row["publishedQuote"] = {k:q[k] for k in ("odds","bookmaker","books","checkedAt","source","referenceOdds")}
            if not re.fullmatch(r"espn:[0-9]+", row["fixtureId"]):
                raise ValueError("Invalid Greek study fixture ID")
            recorded, kickoff = (datetime.fromisoformat(row[k]) for k in ("recordedAt", "date"))
            if (recorded.utcoffset() is None or kickoff.utcoffset() is None or recorded >= kickoff
                    or not qualifies_ticket(qualifies, row)):
                raise ValueError("Invalid pre-match Greek draw selection")
            journal.setdefault(row["fixtureId"], row)
    return sorted(journal.values(), key=lambda p: (datetime.fromisoformat(p["date"]), p["fixtureId"]))
