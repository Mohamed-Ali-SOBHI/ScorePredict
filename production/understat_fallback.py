"""Bounded Understat outage mode. Existing price model only; no sporting imputation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import requests

from inference.english_away_public import fixed_unit_stakes
from inference.live_tracking import append_tracking_rows, build_tracking_rows
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.public_additions import ENGLAND_HOME, select_public_bets
from inference.publication_policy import apply_publication_policy
from inference.result_monitor import update_public_snapshot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'inference/output/understat_fallback'
NOTICE = ('Understat indisponible : nouveaux paris limités à Angleterre domicile. '
          'Les autres stratégies sont en pause ; les paris publiés restent suivis.')


def availability(season, request=requests.get):
    def check(league):
        url = f'https://understat.com/getLeagueData/{league}/{season}'
        try:
            response = request(url, headers={'User-Agent': 'Mozilla/5.0 (ScorePredict)',
                                             'X-Requested-With': 'XMLHttpRequest'}, timeout=15)
            response.raise_for_status()
            if ('text/html' in str(response.headers.get('Content-Type', '')).lower()
                    and '<title>Understat.com</title>' in response.text
                    and 'We will come back soon' in response.text):
                return dict(league=league, available=False, reason='understat_maintenance_page')
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('dates'), list) or not payload.get('teams'):
                raise ValueError('Unexpected Understat payload; not a transport outage')
            return dict(league=league, available=True)
        except requests.exceptions.SSLError:
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return dict(league=league, available=False, reason='connection_unavailable')
        except requests.exceptions.HTTPError as error:
            if error.response is None or error.response.status_code not in {408, 429, 500, 502, 503, 504}:
                raise
            return dict(league=league, available=False, reason=f'http_{error.response.status_code}')
    with ThreadPoolExecutor(max_workers=5) as pool:
        sources = list(pool.map(check, ['Bundesliga', 'EPL', 'Serie_A', 'Ligue_1', 'La_liga']))
    return dict(mode='normal' if all(s['available'] for s in sources) else 'price_only',
                checkedAt=datetime.now(timezone.utc).isoformat(), sources=sources)


def merge_snapshot(snapshot, ledger, now):
    if snapshot.get('meta', {}).get('activePortfolio') != DEFAULT_PORTFOLIO_NAME:
        raise ValueError('Unexpected deployed portfolio')
    result = update_public_snapshot(snapshot, ledger, portfolio_name=DEFAULT_PORTFOLIO_NAME, generated_at=now)
    result['meta']['predictionMode'] = 'price_only_understat_outage'
    result['meta']['serviceNotice'] = NOTICE
    result['meta']['fallbackCheckedAt'] = now.isoformat()
    # Do not relabel the previous complete model run / sporting audit as fresh.
    result.setdefault('quality', {})['sportsAvailable'] = False
    result['quality']['overallStatus'] = 'partial'
    return apply_publication_policy(result)


def run(*args):
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, env=env, check=True, timeout=900)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    temp.replace(path)


def publish(recover_bundesliga=False, manual_review=False):
    from inference.supabase_prediction_store import configuration, pull, push
    if not all(configuration()):
        raise ValueError('Permanent ledger credentials required; refusing a local-only publication')
    now = datetime.now(timezone.utc)
    if not datetime(2026, 7, 1, tzinfo=timezone.utc) <= now < datetime(2027, 7, 1, tzinfo=timezone.utc):
        raise ValueError('Frozen price model requires a season review')
    OUT.mkdir(parents=True, exist_ok=True)
    recover_bundesliga = recover_bundesliga or manual_review
    ledger_path = ROOT / 'inference/output/live_portfolio_bet_log.csv'
    status = OUT / 'store_status.json'
    pull(ledger_path, status, portfolio_name=DEFAULT_PORTFOLIO_NAME)
    existing = pd.read_csv(ledger_path)
    published = {}
    for name in ('dashboard', 'explorer'):
        response = requests.get(f'https://mohamed-ali-sobhi.github.io/ScorePredict/data/{name}.json',
                                params={'run': os.environ.get('GITHUB_RUN_ID', now.isoformat())}, timeout=40)
        response.raise_for_status()
        published[name] = response.json()
    if published['dashboard'].get('activity') and existing.empty:
        raise ValueError('Published history exists but permanent ledger is empty')
    write(OUT / 'previous_dashboard.json', published['dashboard'])
    catalog = OUT / 'fixtures.csv'
    run('-m', 'inference.fetch_sportytrader_portfolio_odds', '--next-24-hours', '--leagues',
        'Bundesliga,EPL' if recover_bundesliga else 'EPL', '--output', catalog)
    scored_path = OUT / 'scored.csv'
    run(ROOT / 'inference/public_additions_worker.py', '--catalog', catalog, '--output', scored_path, '--price-only')
    scored = pd.read_csv(scored_path)
    if not scored.empty:
        if set(scored.strategy_name) != {ENGLAND_HOME} or set(scored.league) != {'EPL'}:
            raise ValueError('Unexpected strategy in outage mode')
        scored['recommended_bet'] = scored.recommended_bet.fillna('')
        scored['date'] = pd.to_datetime(scored.kickoff_utc, utc=True).dt.tz_convert('Europe/Paris')
        # Re-check after collection/model execution so no late decision is recorded.
        now = datetime.now(timezone.utc)
        scored = scored[pd.to_datetime(scored.kickoff_utc, utc=True) >= pd.Timestamp(now) + pd.Timedelta(minutes=5)]
    if recover_bundesliga:
        recovered_path = OUT / 'recovered_bundesliga.csv'
        run('-m', 'production.recover_bundesliga', '--catalog', catalog, '--output', recovered_path,
            *(['--scoped'] if manual_review else []))
        recovered = pd.read_csv(recovered_path)
        if not recovered.empty:
            recovered['recommended_bet'] = recovered.recommended_bet.fillna('')
            recovered['date'] = pd.to_datetime(recovered.kickoff_utc, utc=True).dt.tz_convert('Europe/Paris')
            scored = pd.concat([scored, recovered], ignore_index=True)
    if manual_review:
        from production.manual_match_coverage import prepare
        scope_path = prepare('EPL', OUT)
        english_path = OUT / 'english_manual.csv'
        run(ROOT / 'inference/english_away_worker.py', '--catalog', catalog, '--output', english_path, '--manual-scope', scope_path)
        english = pd.read_csv(english_path)
        if not english.empty:
            english['recommended_bet'] = english.recommended_bet.fillna('')
            english['date'] = pd.to_datetime(english.kickoff_utc, utc=True).dt.tz_convert('Europe/Paris')
            scored = pd.concat([scored, english], ignore_index=True)
    if not scored.empty:
        scored = scored[pd.to_datetime(scored.kickoff_utc, utc=True) >= pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=5)]
    bets = select_public_bets(scored, existing, DEFAULT_PORTFOLIO_NAME)
    bets = fixed_unit_stakes(bets, 2.5)  # Existing 50 EUR * .05 unit, not a stake increase.
    incoming = build_tracking_rows(bets, portfolio_name=DEFAULT_PORTFOLIO_NAME)
    append_tracking_rows(incoming, ledger_path)
    ledger = pd.read_csv(ledger_path)
    dashboard = merge_snapshot(published['dashboard'], ledger, datetime.now(timezone.utc))
    if recover_bundesliga:
        dashboard['meta']['predictionMode'] = 'verified_bundesliga_archive_and_epl_price'
        dashboard['meta']['serviceNotice'] = ('Bundesliga recalculée avec les statistiques sauvegardées et vérifiées. '
                                             'Angleterre extérieur reste en pause.')
        dashboard['meta']['bundesligaRecovery'] = json.loads((OUT / 'recovery_audit.json').read_text(encoding='utf8'))
    if manual_review:
        dashboard['meta']['predictionMode'] = 'manual_per_fixture_archive_review'
        dashboard['meta']['serviceNotice'] = 'Vérification manuelle effectuée. Seuls les matchs aux données complètes ont été recalculés.'
    # Validate only new candidates; older pending tickets retain their publication.
    if not incoming.empty:
        from inference.validate_publication_kickoffs import validate_publication_kickoffs
        new_keys = set(incoming.snapshot_key) - set(existing.snapshot_key)
        import hashlib
        new_ids = {hashlib.sha1(k.encode()).hexdigest()[:12] for k in new_keys}
        validate_publication_kickoffs({'predictions': [p for p in dashboard['predictions'] if p['id'] in new_ids]},
                                     pd.read_csv(catalog))
    else:
        new_keys = set()
    # Validate before the durable write. Any store failure prevents site publication.
    write(OUT / 'dashboard.json', dashboard)
    run('-m', 'inference.publication_policy', '--snapshot', OUT / 'dashboard.json', '--check')
    push(ledger_path, status, portfolio_name=DEFAULT_PORTFOLIO_NAME)
    write(ROOT / 'production/static/data/dashboard.json', dashboard)
    explorer = published['explorer']
    explorer.setdefault('meta', {})['serviceNotice'] = 'Analyses sportives en pause : Understat indisponible.'
    explorer['meta']['predictionMode'] = 'price_only_understat_outage'
    # Preserve its old timestamp: no stale sporting probability is presented as new.
    write(ROOT / 'production/static/data/explorer.json', explorer)
    scored.to_csv(OUT / 'all_reviewed_predictions.csv', index=False)
    write(OUT / 'report.json', dict(mode=dashboard['meta']['predictionMode'], newBets=len(new_keys),
                                  scoredFixtures=int(scored.fixture_id.nunique()) if not scored.empty else 0,
                                  strategyRows=len(scored),
                                  historyRows=len(ledger), checkedAt=datetime.now(timezone.utc).isoformat()))
    print({'temporary_mode': dashboard['meta']['predictionMode'], 'new_bets': len(new_keys), 'scored': len(scored)}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'publish'])
    parser.add_argument('--recover-bundesliga', action='store_true', help='Explicit recovery with archive completeness checks')
    parser.add_argument('--manual-review', action='store_true', help='Explicit review of each fixture history and Elo dependencies')
    args = parser.parse_args()
    if args.action == 'publish':
        publish(args.recover_bundesliga, args.manual_review)
        return
    now = datetime.now(timezone.utc)
    health = availability(now.year if now.month >= 7 else now.year - 1)
    write(OUT / 'availability.json', health)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as stream:
            stream.write(f"mode={health['mode']}\n")
    print(json.dumps(health))


if __name__ == '__main__':
    main()
