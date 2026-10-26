"""Calendar quarantine distinguishes committed bets from verified abstentions.

Keep the v1 timestamp resolver and all sealed forecasts intact. An unresolved
calendar is never settled. Only verified abstentions may be nonblocking.
"""
from __future__ import annotations
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from production import paper_settlement_runtime as v1

VERSION = 'paper_calendar_quarantine_v2_2026_10_26'
MANIFEST = Path(__file__).with_suffix('.json')
TIME_ERRORS = {
    'Archived timestamp cannot establish its timezone',
    'Cannot infer a naive result time from an offset-only archive',
    'Ambiguous or nonexistent result timestamp',
}


def confirmed_abstention(forecast):
    portfolios = forecast.get('portfolios')
    decisions = forecast.get('decisions')
    return (isinstance(portfolios, dict) and bool(portfolios)
            and all(bet is None for bet in portfolios.values())
            and isinstance(decisions, list) and bool(decisions)
            and all(isinstance(choice, dict) and choice.get('selected') is False for choice in decisions)
            and 'reference' in forecast and forecast['reference'] is None)


def normalize_settlement_sources(state, forecasts, sources):
    normalized, audit = v1.normalize_settlement_sources(state, forecasts, sources)
    warnings = []
    for item in audit['unresolved']:
        forecast = forecasts[item['fixture_id']]
        games = [g for g in sources.get(forecast['league'], {}).get('dates', [])
                 if 'understat:' + str(g['id']) == item['fixture_id']]
        if (item['reason'] in TIME_ERRORS and confirmed_abstention(forecast)
                and len(games) == 1 and str(games[0]['h']['id']) == forecast['home_id']
                and str(games[0]['a']['id']) == forecast['away_id']):
            warnings.append(dict(item, action='quarantined_without_settlement',
                                 committed_bets=0, selected_decisions=0,
                                 verified_kickoff_utc=forecast['kickoff_utc'],
                                 observed_datetime=games[0]['datetime']))
    # v1 still excludes every unresolved fixture before calling the collector.
    audit['nonblocking_abstentions'] = warnings
    return normalized, audit


def settle_normalized(original_settle, journal, sources, metadata, audit):
    count, issues = v1.settle_normalized(original_settle, journal, sources, metadata, audit)
    abstentions = {item['fixture_id'] for item in audit.get('nonblocking_abstentions', [])}
    return count, [issue for issue in issues if not (
        issue['fixture_id'] in abstentions and issue['reason'] == 'settlement_timezone_unresolved')]


def screen_candidates(candidates, sources):
    accepted = []; rejected = []
    for fixture in candidates:
        try:
            games = [g for g in sources[fixture['league']]['dates']
                     if 'understat:' + str(g['id']) == fixture['fixture_id']]
            if len(games) != 1:
                raise ValueError('No unique source event')
            raw_time = games[0]['datetime']
            instant, _ = v1.resolve(raw_time, raw_time, fixture['kickoff_utc'], fixture['league'])
            if abs((instant - v1.utc(fixture['kickoff_utc'])).total_seconds()) > 1800:
                raise ValueError('Source kickoff differs from canonical schedule')
            accepted.append(fixture)
        except (ValueError, KeyError) as error:
            rejected.append({'fixture_id': fixture['fixture_id'],
                             'reason': 'schedule_conflict_before_capture', 'detail': str(error)})
    return accepted, rejected


def verify_amendment(experiment, registration):
    # The original amendment remains verifiable at its original exact hash.
    v1.verify_amendment(experiment, registration)
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    if (manifest['version'] != VERSION
            or manifest['runtime_sha256'] != v1.digest_bytes(Path(__file__).read_bytes())
            or manifest['parent_manifest_sha256'] != v1.digest_bytes(v1.MANIFEST.read_bytes())):
        raise ValueError('Calendar amendment changed; register a new version')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', choices=['paper_simulation','paper_positive15'], required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Live paper settlement runs on GitHub Actions only')
    sys.path.insert(0, str(v1.ROOT / args.experiment))
    collector = importlib.import_module('run_paper')
    manifest = verify_amendment(args.experiment, collector.check_registration())
    original_collect, original_settle = collector.collect, collector.settle
    original_candidates = collector.identify_candidates
    context = {}
    def collect(batch):
        result = original_collect(batch); context['batch'] = batch
        return result
    def candidates(sources, catalog):
        fixtures, rejected = original_candidates(sources, catalog)
        accepted, conflicts = screen_candidates(fixtures, sources)
        return accepted, rejected + conflicts
    def settle(journal, sources, metadata):
        normalized, audit = normalize_settlement_sources(collector.STATE, journal.records('forecast'), sources)
        audit.update(version=VERSION, runtime_sha256=manifest['runtime_sha256'],
                     amendment_sha256=v1.digest_bytes(MANIFEST.read_bytes()),
                     source_snapshot_sha256={k:v['sha256'] for k,v in metadata.items()},
                     github_run_id=os.environ.get('GITHUB_RUN_ID'))
        collector.write(context['batch'] / 'settlement_runtime.json', audit)
        journal.append('run', VERSION + ':' + context['batch'].name, audit)
        for item in audit['nonblocking_abstentions']:
            print('::warning::Unresolved calendar for ' + item['fixture_id']
                  + '; verified abstention (0 bets), no settlement created.', flush=True)
        return settle_normalized(original_settle, journal, normalized, metadata, audit)
    collector.collect, collector.identify_candidates, collector.settle = collect, candidates, settle
    collector.main()


if __name__ == '__main__':
    main()
