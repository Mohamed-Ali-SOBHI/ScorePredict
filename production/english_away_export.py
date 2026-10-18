"""Private prospective readout of a preregistered filter on sealed forecasts.

The source collector already archives logit sports forecasts before kickoff.
This observer never changes a source decision, trains a model or backfills a bet.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

from production import observation_export as ex

REGISTRATION = ex.ROOT / 'production/english_away_registration.json'
OUTPUT = ex.ROOT.parent / 'suivi_prive_9/angleterre_exterieur_strict.json'
RULE = {'league': 'EPL', 'model': 'logit_sports', 'outcome': 'away',
        'odds_min': 2, 'odds_max': 6, 'ev_threshold': .10, 'price_haircut': .02}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Explicit UTC offset required')
    return result.astimezone(timezone.utc)


def read_registration():
    registration = ex.read(REGISTRATION)
    if registration['observer_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or registration['rule'] != RULE:
        raise ValueError('Registered English observer changed; retain this version and register a new one.')
    return registration


def verify_chain(events, source_registration_hash):
    prior = source_registration_hash
    identities = set()
    for index, event in enumerate(events, 1):
        key = event['kind'], event['identity']
        if event['seq'] != index or key in identities or event['previous_hash'] != prior:
            raise ValueError('Invalid source chronology')
        identities.add(key)
        payload = {k: event[k] for k in ['kind', 'identity', 'payload', 'previous_hash']}
        if digest(payload) != event['event_hash']:
            raise ValueError('Changed source event')
        prior = event['event_hash']


def verify_source(folder, registration):
    folder = Path(folder)
    source_registration = ex.read(folder / 'registration.json')
    expected = registration['source_registration_sha256']
    if digest(source_registration) != expected:
        raise ValueError('Wrong source experiment')
    source_root = ex.ROOT / 'paper_simulation'
    if ex.read(source_root / 'registration.json') != source_registration:
        raise ValueError('Source registration differs from the frozen collector')
    for name, sha in source_registration['frozen_sha256'].items():
        if hashlib.sha256((source_root / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Frozen source model or code changed: ' + name)
    checkpoint = ex.read(folder / 'checkpoint.json')
    files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(folder.rglob('*')) if p.is_file() and '.git' not in p.relative_to(folder).parts
             and p.name not in {'checkpoint.json', 'collector.lock'}}
    if checkpoint['registration_sha256'] != expected or checkpoint['files'] != files:
        raise ValueError('Source inventory changed')
    evidence = ex.read(folder / 'evidence.json')
    events = evidence['events']
    if evidence['registration_sha256'] != expected or checkpoint['event_count'] != len(events) or checkpoint['events_sha256'] != digest(events):
        raise ValueError('Source checkpoint mismatch')
    verify_chain(events, expected)
    db = sqlite3.connect((folder / 'journal.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        actual = [{'seq': s, 'kind': k, 'identity': i, 'payload': json.loads(p), 'previous_hash': h, 'event_hash': e}
                  for s, k, i, p, h, e in db.execute('SELECT * FROM events ORDER BY seq')]
    finally:
        db.close()
    if actual != events:
        raise ValueError('Source SQLite journal differs from evidence')
    return events, checkpoint, ex.read(folder / 'report.json')['status']


def metrics(tickets):
    settled = [t for t in tickets if t['status'] in {'won', 'lost'}]
    profit = sum(t['profit'] for t in settled)
    return {'settled': len(settled), 'pending': sum(t['status'] == 'pending' for t in tickets),
            'wins': sum(t['status'] == 'won' for t in settled), 'profit': round(profit, 8),
            'roi': profit / len(settled) if settled else None}


def union_tickets(reference, english):
    # A fixture has one stake, including when two strategies disagree on outcome.
    result = {t['fixture_id']: t for t in reference}
    for ticket in english:
        result.setdefault(ticket['fixture_id'], ticket)
    return list(result.values())


def build(events, checkpoint, source_status, registration, now=None):
    now = now or datetime.now(timezone.utc)
    verify_chain(events, registration['source_registration_sha256'])
    prefix_count = registration['source_prefix']['event_count']
    if len(events) < prefix_count or digest(events[:prefix_count]) != registration['source_prefix']['events_sha256']:
        raise ValueError('History predating English enrollment changed')
    activation = stamp(registration['registered_at_utc'])
    forecasts = {}; results = {}
    for event in events:
        if event['kind'] == 'forecast':
            forecasts[event['identity']] = event
        elif event['kind'] == 'settlement':
            if event['identity'] not in forecasts:
                raise ValueError('Result without forecast')
            result = event['payload']; forecast = forecasts[event['identity']]['payload']
            if result['forecast_sha256'] != digest(forecast) or not stamp(forecast['kickoff_utc']) + timedelta(hours=2) <= stamp(result['result_seen_at_utc']) <= now:
                raise ValueError('Result does not match the recorded forecast')
            hg, ag = result['home_goals'], result['away_goals']
            expected = 'home' if hg > ag else 'away' if hg < ag else 'draw'
            if result['outcome'] != expected:
                raise ValueError('Result score/outcome mismatch')
            results[event['identity']] = result
    baseline = []; english = []; enrolled = []
    rule = registration['rule']
    for identity, event in forecasts.items():
        f = event['payload']; created = stamp(f['recorded_at_utc']); kickoff = stamp(f['kickoff_utc'])
        # No pre-enrollment source forecasts, even when the fixture is still future.
        if event['seq'] <= prefix_count or created < activation:
            continue
        if not activation <= created <= now or not timedelta(minutes=5) <= kickoff - created <= timedelta(hours=24):
            raise ValueError('Forecast is outside the prospectively recorded window')
        if f['registration_sha256'] != registration['source_registration_sha256']:
            raise ValueError('Forecast source version changed')
        quote_time = stamp(f['quotes_collected_at_utc'])
        if not timedelta(0) <= created - quote_time <= timedelta(minutes=30):
            raise ValueError('Stale source quote')
        enrolled.append(identity)
        selected = None
        if f['league'] == 'Bundesliga' and f.get('reference'):
            ref = f['reference']
            if ref['outcome'] != 'draw' or stamp(ref['generated_at_utc']) > created:
                raise ValueError('Non-prospective public Bundesliga reference')
            selected = ('reference', 'draw', float(ref['odds']))
        elif f['league'] == rule['league']:
            probability = f['probabilities'][rule['model']]
            if set(probability) != {'away', 'draw', 'home'} or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probability.values()) or abs(sum(probability.values()) - 1) > 1e-6:
                raise ValueError('Invalid recorded model probabilities')
            odds = float(f['odds'][rule['outcome']])
            if not math.isfinite(odds):
                raise ValueError('Invalid recorded odds')
            if rule['odds_min'] <= odds <= rule['odds_max'] and probability[rule['outcome']] * odds * (1 - rule['price_haircut']) - 1 > rule['ev_threshold']:
                selected = (registration['strategy_id'], rule['outcome'], odds)
        if selected is None:
            continue
        source, outcome, odds = selected
        if odds <= 1:
            raise ValueError('Invalid ticket odds')
        settlement = results.get(identity)
        status = 'pending' if settlement is None else 'won' if settlement['outcome'] == outcome else 'lost'
        ticket = {'fixture_id': identity, 'date': f['kickoff_utc'], 'home': f['home_team'], 'away': f['away_team'],
                  'league': f['league'], 'strategy': source, 'outcome': outcome, 'odds': odds, 'stake': 1,
                  'status': status, 'profit': None if settlement is None else odds - 1 if status == 'won' else -1,
                  'forecast_recorded_at': f['recorded_at_utc'], 'source_forecast_sha256': digest(f),
                  'actual_score': None if settlement is None else f"{settlement['home_goals']} - {settlement['away_goals']}"}
        (baseline if source == 'reference' else english).append(ticket)
    union = union_tickets(baseline, english)
    latest = stamp(source_status['finished_at_utc'])
    status = 'awaiting_capture' if latest < activation else 'ready' if source_status['state'] == 'collected' else 'attention'
    return {'schemaVersion': 1, 'private': True, 'strategyId': registration['strategy_id'],
            'code': 'E02', 'label': 'Angleterre · extérieur logistique · filtre strict', 'rule': rule,
            'registeredAt': registration['registered_at_utc'], 'updatedAt': datetime.now(timezone.utc).isoformat(),
            'sourceUpdatedAt': source_status['finished_at_utc'], 'status': status,
            'sourceEvidenceHash': checkpoint['events_sha256'], 'sourcePrefixVerified': True,
            'enrolledFixtures': len(enrolled), 'metrics': metrics(english),
            'baseline': metrics(baseline), 'union': metrics(union), 'tickets': english, 'unionTickets': union,
            'scope': 'Premières captures source après activation, mêmes matchs observables pour la référence. Aucun historique de simulation ajouté au suivi prospectif.',
            'stakeUnits': 1, 'history': registration['retrospective_history']}


def snapshot(source_state=None):
    try:
        registration = read_registration()
        if source_state is not None:
            events, checkpoint, status = verify_source(source_state, registration)
            result = build(events, checkpoint, status, registration)
        else:
            with tempfile.TemporaryDirectory(prefix='english-away-private-') as tmp:
                source = Path(tmp) / 'source'
                ex.fetch_state('simulation-state', source)
                events, checkpoint, status = verify_source(source, registration)
                result = build(events, checkpoint, status, registration)
        ex.require_private_output(OUTPUT)
        ex.atomic_write(OUTPUT, result)
        return result
    except Exception as error:
        print('English observation unavailable:', str(error))
        return {'status': 'unavailable', 'message': 'La collecte Angleterre extérieur ne peut pas être vérifiée.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-state', type=Path)
    args = parser.parse_args()
    result = snapshot(args.source_state)
    print('English away private observation:', result['status'])


if __name__ == '__main__':
    main()
