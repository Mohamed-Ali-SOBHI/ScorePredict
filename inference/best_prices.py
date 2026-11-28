"""Nominal full-time 1X2 offers. The model's reference market stays separate from the ticket."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "inference/output/best_prices/coteur.json"
MAX_AGE = timedelta(minutes=30)
NOTE_MARKER = " | coteur="
ALIASES = {
    "fsv mainz 05":"mainz 05", "hambourg sv":"hamburger sv", "sv elversberg 07":"elversberg",
    "sc friburg":"freiburg", "eintracht francfort":"eintracht frankfurt",
    "nottingham":"nottingham forest", "werder breme":"werder bremen",
    "kifisias ae":"kifisia", "volos nps":"volos nfc", "iraklis saloniki":"iraklis",
    "pot iraklis":"iraklis", "panaitolikos":"panetolikos", "atromitos athinon":"atromitos",
    "paok salonique":"paok", "aris saloniki":"aris", "aek":"aek athens",
    "asteras tripolis":"asteras tripoli", "levadeiakos":"levadiakos", "olympiakos":"olympiacos",
}

def utcnow():
    return datetime.now(timezone.utc)

def is_recent(value, now):
    try:
        return timedelta(0) <= now - datetime.fromisoformat(value) <= MAX_AGE
    except (TypeError, ValueError):
        return False

def capture():
    if CAPTURE.exists():
        try:
            data = json.loads(CAPTURE.read_text(encoding="utf-8"))
            if is_recent(data["capturedAt"], utcnow()):
                return data["records"]
        except (OSError, ValueError, KeyError):
            pass
    try:
        subprocess.run(["node", str(ROOT/"inference/coteur_prices.mjs"), str(CAPTURE)], cwd=ROOT, check=True, timeout=240)
        return json.loads(CAPTURE.read_text(encoding="utf-8"))["records"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        print(f"::warning::Comparateur indisponible ({type(error).__name__}).")
        return []

def club(value):
    from inference.espn_results import team_name
    n = team_name(value)
    return ALIASES.get(n, n)

def match_offers(records, league, home, away, kickoff, outcome, now):
    when = datetime.fromisoformat(str(kickoff))
    if when.utcoffset() is None or when <= now:
        return []
    matches = [r for r in records if r["league"] == league and datetime.fromisoformat(r["kickoff"]) == when
               and club(r["home"]) == club(home) and club(r["away"]) == club(away)]
    if len(matches) != 1 or not is_recent(matches[0]["at"], now):
        return []
    record = matches[0]
    if not re.fullmatch(r"/cote/[\w-]+-\d+", record["href"]):
        return []
    books = {}
    for row in record["offers"]:
        price = row["prices"].get(outcome)
        if isinstance(price, (int, float)) and math.isfinite(price) and price > 1 and row["book"]:
            books.setdefault(row["book"], set()).add(price)
    valid = [(name, next(iter(prices))) for name, prices in books.items() if len(prices) == 1]
    return [dict(bookmaker=b, odds=v, checkedAt=record["at"], books=len(valid), source="https://www.coteur.com"+record["href"])
            for b,v in sorted(valid, key=lambda pair: (-pair[1], pair[0]))]

def note(original, offer):
    return str(original or "").split(NOTE_MARKER)[0] + NOTE_MARKER + json.dumps(offer, ensure_ascii=False, separators=(",", ":"))

def public_quote(original):
    parts = str(original or "").partition(NOTE_MARKER)
    if not parts[1]:
        return {}
    return {"publishedQuote": json.loads(parts[2])}

def qualifies_at_offer(rule, probability, reference, offered, *args):
    """The reference price defines the model's domain. A better execution price only improves EV."""
    try:
        price, baseline = float(offered), float(reference)
    except (TypeError, ValueError):
        return False
    return (math.isfinite(price) and rule(probability, baseline, *args)
            and (price >= baseline or rule(probability, price, *args)))

def qualifies_ticket(rule, row):
    price = row.get("odds", row.get("selected_odds"))
    probability = row.get("modelProbability", row.get("predicted_probability"))
    quote = row.get("publishedQuote") or public_quote(row.get("probability_note")).get("publishedQuote")
    if not quote:
        return rule(probability, price)
    return quote.get("odds") == price and qualifies_at_offer(rule, probability, quote.get("referenceOdds"), price)

def apply_prices(scored, records, now):
    """Preserve reference-model eligibility and confirm the selected outcome at the available price."""
    from inference.english_away_public import STRATEGY as AWAY, qualifies as away_qualifies
    from inference.public_additions import ENGLAND_HOME, qualifies
    from inference.bundesliga_draw_public import qualifies as draw_qualifies
    result = scored.copy()
    if result.empty:
        return result
    selected = result["recommended_bet"].fillna("").ne("")
    for idx, row in result.loc[selected].iterrows():
        league, outcome, strategy = row["league"], row["selected_outcome"], row["strategy_name"]
        if not (strategy in (AWAY, ENGLAND_HOME) or (league == "Bundesliga" and outcome == "draw" and "__filter_" in strategy)):
            continue
        result.at[idx,"recommended_bet"] = ""
        if datetime.fromisoformat(str(row["kickoff_utc"])) - now < timedelta(minutes=5):
            continue
        quotes = match_offers(records, league, row["team_name"], row["opponent_name"], row["kickoff_utc"], outcome, now)
        p = float(row["predicted_probability"])
        if not quotes:
            continue
        best = quotes[0]
        price = best["odds"]
        reference = float(row["selected_odds"])
        if strategy == AWAY:
            eligible = qualifies_at_offer(away_qualifies, p, reference, price)
        elif strategy == ENGLAND_HOME:
            eligible = qualifies_at_offer(qualifies, p, reference, price)
        else:
            eligible = qualifies_at_offer(draw_qualifies, p, reference, price, row["market_probability"])
        if eligible:
            raw_ev = p * price - 1
            result.at[idx,"recommended_bet"] = outcome
            result.at[idx,"selected_odds"] = price
            result.at[idx,"raw_expected_value"] = raw_ev
            result.at[idx,"expected_value"] = raw_ev if league == "Bundesliga" else p*price*.98-1
            result.at[idx,"probability_note"] = note(row.get("probability_note"), dict(best,referenceOdds=reference))
    print(f"Cotes comparées : {int(selected.sum())} sélections initiales, "
          f"{int(result['recommended_bet'].fillna('').ne('').sum())} confirmées.")
    return result

def dashboard_offers(snapshot, records, now):
    updates = []
    picks = list(snapshot["predictions"]) + [dict(p,league="G1",outcome="draw") for p in snapshot["greekDrawStudy"]]
    for pick in picks:
        outcome = pick.get("outcome")
        if not outcome:
            continue
        quotes = match_offers(records,pick["league"],pick["homeTeam"],pick["awayTeam"],pick["date"],outcome,now)
        if quotes:
            updates.append({k:pick[k] for k in ("league","homeTeam","awayTeam","date","outcome")} | quotes[0])
    return updates
