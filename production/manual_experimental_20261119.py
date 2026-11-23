"""One-off, explicitly authorised publication of four experimental selections.

The receipt is a frozen manual calculation, not a routine automated recovery.
The durable ledger is checked before writing and prior decisions are not rewritten.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math

import pandas as pd
import requests

from inference.english_away_public import STRATEGY as EPL_AWAY, fixed_unit_stakes, qualifies as away_qualifies
from inference.espn_results import fetch_scoreboard, team_name
from inference.live_tracking import build_tracking_rows, canonicalize_tracking_rows
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.public_additions import BUNDESLIGA, qualifies as bundesliga_qualifies
from inference.publication_policy import apply_publication_policy, public_row
from inference.supabase_prediction_store import configuration, pull, remote_records, request_headers
from production.understat_fallback import EXPERIMENT_NOTICE, merge_snapshot, write

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'production/recovery/experimental-2026-11-19.json'
EXPECTED = {
    ('Bundesliga', 'Eintracht Frankfurt', 'Hoffenheim', 'draw'),
    ('Bundesliga', 'Elversberg', 'Freiburg', 'draw'),
    ('EPL', 'Chelsea', 'Leeds', 'away_win'),
    ('EPL', 'Tottenham', 'Ipswich', 'away_win'),
}
NOTE = 'manual_weekend_wbookie_20261119__experimental_sportmonks_20261119'


def candidate_rows(receipt, boards, now):
    prepared = datetime.fromisoformat(receipt['preparedAtUtc'])
    if not timedelta(0) <= now - prepared <= timedelta(hours=3):
        raise ValueError('Manual verification expired or future-dated')
    if receipt.get('fixtureDate') != '2026-11-21' or len(receipt['picks']) != 4:
        raise ValueError('Unexpected scope')
    identities = {(p['league'], p['home'], p['away'], p['outcome']) for p in receipt['picks']}
    if identities != EXPECTED or len({p['fixture_id'] for p in receipt['picks']}) != 4:
        raise ValueError('Unexpected or duplicate fixture')
    rows = []
    for item in receipt['picks']:
        home, away = item['home'], item['away']
        league, outcome = item['league'], item['outcome']
        expected_strategy = BUNDESLIGA if league == 'Bundesliga' else EPL_AWAY
        if item['strategy'] != expected_strategy:
            raise ValueError('Strategy mismatch')
        board = boards[league]
        matched = board[(board.home_team_norm == team_name(home)) & (board.away_team_norm == team_name(away))]
        if len(matched) != 1:
            raise ValueError('Independent fixture check failed: ' + home)
        kickoff = pd.Timestamp(matched.iloc[0].official_date).tz_localize('Europe/Paris').tz_convert('UTC')
        if kickoff != pd.Timestamp(item['kickoff']) or kickoff <= pd.Timestamp(now) + pd.Timedelta(minutes=5):
            raise ValueError('Kickoff mismatch or match too close: ' + home)
        odds = [float(o) for o in item['odds']]
        if len(odds) != 3 or any(not math.isfinite(o) or o <= 1 for o in odds):
            raise ValueError('Invalid price')
        price = odds[1 if outcome == 'draw' else 2]
        p = float(item['probability'])
        if not (bundesliga_qualifies(p, price) if league == 'Bundesliga' else away_qualifies(p, price)):
            raise ValueError('Selection does not meet its frozen filter: ' + home)
        market = (1 / price) / sum(1 / o for o in odds)
        rows.append(dict(fixture_id=item['fixture_id'], kickoff_utc=kickoff.isoformat(),
                         date=kickoff.tz_convert('Europe/Paris'), league=league,
                         team_name=home, opponent_name=away, strategy_name=item['strategy'],
                         strategy_names=item['strategy'], selected_outcome=outcome, selected_odds=price,
                         predicted_probability=p, raw_model_probability=p, market_probability=market,
                         edge=p-market, value_score=p/market, expected_value=p*price*.98-1,
                         raw_expected_value=p*price-1, probability_note=NOTE, train_max_season=2024,
                         recommended_bet=outcome))
    return pd.DataFrame(rows)


def exclude_held(candidates, existing):
    """Never rewrite or add any second outcome on an already published fixture."""
    if existing.empty:
        return candidates.copy()
    existing = existing[existing.portfolio_name.eq(DEFAULT_PORTFOLIO_NAME)].copy()
    held_ids = set(existing.fixture_id.fillna('').astype(str))
    held = {(str(r.league), team_name(r.team_name), team_name(r.opponent_name),
             pd.Timestamp(r.date).date()) for r in existing.itertuples()}
    keep = [(r.fixture_id not in held_ids and
             (r.league, team_name(r.team_name), team_name(r.opponent_name), pd.Timestamp(r.date).date()) not in held)
            for r in candidates.itertuples()]
    return candidates.loc[keep].copy().reset_index(drop=True)


def main():
    now = datetime.now(timezone.utc)
    receipt = json.loads(RECEIPT.read_text(encoding='utf8'))
    url, key = configuration()
    if not url or not key:
        raise ValueError('Permanent store unavailable')
    out = ROOT / 'inference/output/understat_fallback'; out.mkdir(parents=True, exist_ok=True)
    ledger_path, status = out/'experimental_ledger.csv', out/'experimental_store.json'
    pull(ledger_path, status, portfolio_name=DEFAULT_PORTFOLIO_NAME)
    existing = pd.read_csv(ledger_path)
    endpoint = 'https://mohamed-ali-sobhi.github.io/ScorePredict/data/'
    snapshots = {}
    for name in ('dashboard', 'explorer'):
        response = requests.get(endpoint + name + '.json', params={'manual': now.isoformat()}, timeout=40)
        response.raise_for_status(); snapshots[name] = response.json()
    if snapshots['dashboard'].get('activity') and existing.empty:
        raise ValueError('Published history missing from permanent store')
    boards = {league: fetch_scoreboard(league, receipt['fixtureDate']) for league in ('Bundesliga', 'EPL')}
    candidates = candidate_rows(receipt, boards, now)
    candidates = candidates.loc[candidates.strategy_name.ne(BUNDESLIGA)]
    bets = fixed_unit_stakes(exclude_held(candidates, existing), 2.5)
    incoming = build_tracking_rows(bets, portfolio_name=DEFAULT_PORTFOLIO_NAME)
    combined = canonicalize_tracking_rows(pd.concat([existing, incoming], ignore_index=True)) if not incoming.empty else existing
    snapshot = merge_snapshot(snapshots['dashboard'], combined, now)
    snapshot['meta']['serviceNotice'] = EXPERIMENT_NOTICE
    snapshot['meta']['predictionMode'] = 'experimental_sportmonks_understat_outage'
    # Existing settled and pending decisions remain present and unmodified.
    old_activity = {a['id']: a for a in snapshots['dashboard'].get('activity', [])}
    new_activity = {a['id']: a for a in snapshot.get('activity', [])}
    for identity, before in old_activity.items():
        if identity not in new_activity or any(new_activity[identity].get(k) != before.get(k) for k in ('status', 'outcome', 'odds', 'profitUnits')):
            raise ValueError('An existing published result would change: ' + str(identity))
    expected_ids = {hashlib.sha1(k.encode()).hexdigest()[:12] for k in incoming.get('snapshot_key', [])}
    seen = {p['id'] for p in snapshot.get('predictions', []) if p.get('earlyPublished') is True}
    if not expected_ids.issubset(seen) or not all(public_row(p) for p in snapshot.get('predictions', [])):
        raise ValueError('Experimental selections are not present in the validated snapshot')
    if incoming.empty:
        print('No new bets; existing decisions preserved')
    else:
        response = requests.post(f'{url}/rest/v1/prediction_history', headers=request_headers(key, upsert=True),
                                 params={'on_conflict':'snapshot_key'}, json=remote_records(incoming), timeout=30)
        response.raise_for_status()
    write(ROOT/'production/static/data/dashboard.json', snapshot)
    write(ROOT/'production/static/data/explorer.json', snapshots['explorer'])
    write(out/'experimental-weekend-report.json', dict(checkedAt=now.isoformat(), source=receipt['quoteSource'],
        priceSnapshot=receipt['quoteSnapshotUtc'], experimentalSportsSource=receipt['sportsSource'],
        candidates=len(candidates), added=len(incoming), skipped=len(candidates)-len(incoming),
        matches=[{'home': r.team_name, 'away': r.opponent_name, 'outcome': r.selected_outcome,
                  'odds': r.selected_odds} for r in incoming.itertuples()]))
    print('Experimental selections added:', len(incoming))


if __name__ == '__main__':
    main()
