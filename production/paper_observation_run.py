"""Route a paper run according to the evidence from its production run."""
import argparse
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from production import paper_source_runtime_v3 as runtime

CATALOG = 'sportytrader_upcoming_portfolio_odds.csv'
AVAILABILITY = 'inference/output/understat_fallback/availability.json'
PAUSED = 'paused_understat_unavailable'


def outage_status(evidence, production_run_id, now):
    """Return a pause only for a recent, explicit production outage report."""
    probe = json.loads((evidence / AVAILABILITY).read_text(encoding='utf8'))
    if probe['mode'] == 'normal':
        return None
    checked = datetime.fromisoformat(probe['checkedAt'])
    sources = probe['sources']
    leagues = {'Bundesliga', 'EPL', 'Serie_A', 'Ligue_1', 'La_liga'}
    if (probe['mode'] != 'price_only' or len(sources) != len(leagues)
            or {s['league'] for s in sources} != leagues
            or any(type(s['available']) is not bool for s in sources)
            or not timedelta(0) <= now - checked <= timedelta(hours=24)):
        raise ValueError('Invalid or stale production availability report')
    unavailable = {s['league']: s['reason'] for s in sources if not s['available']}
    if not unavailable or not all(unavailable.values()):
        raise ValueError('Missing reason for restricted production')
    return dict(state=PAUSED, production_run_id=production_run_id, sources=unavailable,
                availability_checked_at_utc=checked.isoformat(), finished_at_utc=now.isoformat(),
                new_forecasts=0, new_settlements=0, production_changed=False,
                github_run_id=os.environ.get('GITHUB_RUN_ID'),
                github_run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'))


def prepare(collector, registration):
    # production_snapshot verifies the artifact hashes and the frozen production
    # manifest before looking up the calendar. This cache belongs to this call.
    try:
        snapshot = collector.production_snapshot(registration)
    except ValueError as error:
        if str(error) != 'Missing/ambiguous evidence file: ' + CATALOG:
            raise
        markers = list(collector.CACHE.glob('*/verified_files.json'))
        if len(markers) != 1:
            raise
        evidence = markers[0].parent
        hashes = json.loads(markers[0].read_text(encoding='utf8'))
        if AVAILABILITY not in hashes or any(
                Path(name).name == CATALOG and 'shadow' not in Path(name).parts for name in hashes):
            raise
        pause = outage_status(evidence, evidence.name, datetime.now(timezone.utc))
        if pause is None:
            raise
        return None, pause
    run, _, _, hashes = snapshot
    if AVAILABILITY in hashes:
        pause = outage_status(collector.CACHE / str(run['databaseId']), run['databaseId'],
                              datetime.now(timezone.utc))
        if pause is not None:
            return None, pause
    return snapshot, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', choices=['paper_simulation', 'paper_positive15'], required=True)
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Live observations run on GitHub Actions only')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / args.experiment))
    collector = importlib.import_module('run_paper')
    if args.health:
        importlib.import_module('cloud_state').verify()
        status = json.loads((collector.STATE / 'report.json').read_text(encoding='utf8'))['status']
        if (status['state'] not in ('collected', PAUSED)
                or status.get('github_run_id') != os.environ['GITHUB_RUN_ID']
                or status.get('github_run_attempt') != os.environ['GITHUB_RUN_ATTEMPT']):
            raise ValueError('Paper run needs attention: ' + status['state'])
        print(status['state'])
        return
    registration = collector.check_registration()
    runtime.verify_amendment()
    runtime.v2.verify_amendment(args.experiment, registration)
    with TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as cache:
        collector.CACHE = Path(cache)
        snapshot, pause = prepare(collector, registration)
        if pause is None:
            # Supply the exact verified snapshot even if another daily job finishes now.
            collector.production_snapshot = lambda registration: snapshot
            runtime.main()
            return
        collector.write(collector.STATE / 'last_run.json', pause)
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as output:
            print('paused=true', file=output)
        print('::notice::Collecte et règlement différés. Understat indisponible pour '
              + ', '.join(pause['sources']) + f" (production {pause['production_run_id']}).")


if __name__ == '__main__':
    main()
