"""Versioned settlement adapter; all sealed forecasts, models and code stay intact.

An archived pre-match Understat timestamp anchors its timezone to the verified
UTC kickoff. Only the settlement input is normalized. A moved or ambiguous
kickoff still goes through the original quarantine checks.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name('paper_settlement_runtime_v1.json')
VERSION = 'understat_settlement_timezone_v1_2026_10_18'
ZONES = {'Ligue_1': 'Europe/Paris', 'EPL': 'Europe/London',
         'Bundesliga': 'Europe/Berlin', 'Serie_A': 'Europe/Rome', 'La_liga': 'Europe/Madrid'}


def digest_bytes(content):
    return hashlib.sha256(content).hexdigest()


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Verified kickoff needs an explicit timezone')
    return parsed.astimezone(timezone.utc)


def instants(wall_time, zone):
    """Reject nonexistent local times; retain both folds of an ambiguous time."""
    result = set()
    for fold in (0, 1):
        candidate = wall_time.replace(tzinfo=ZoneInfo(zone), fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(ZoneInfo(zone)).replace(tzinfo=None) == wall_time:
            result.add(candidate)
    return result


def resolve(initial, observed, kickoff, league):
    anchor = utc(kickoff)
    first = datetime.fromisoformat(initial.replace('Z', '+00:00'))
    current = datetime.fromisoformat(observed.replace('Z', '+00:00'))
    if current.tzinfo is not None:
        return current.astimezone(timezone.utc), 'explicit_offset'
    if first.tzinfo is not None:
        raise ValueError('Cannot infer a naive result time from an offset-only archive')
    choices = []
    for zone in dict.fromkeys(['UTC', ZONES[league]]):
        possible = ({first.astimezone(timezone.utc)} if first.tzinfo is not None
                    and zone == 'UTC' else instants(first, zone) if first.tzinfo is None else set())
        if anchor in possible:
            choices.append(zone)
    if not choices:
        raise ValueError('Archived timestamp cannot establish its timezone')
    # UTC and winter London can coincide; they describe the same instant.
    resolved = {time for zone in choices for time in instants(current, zone)}
    if len(resolved) > 1 and current == first and anchor in resolved:
        resolved = {anchor}
    if len(resolved) != 1:
        raise ValueError('Ambiguous or nonexistent result timestamp')
    return resolved.pop(), choices[0]


def archived_game(state, forecast, cache):
    relative = Path(forecast['capture_directory']) / (forecast['league'] + '.json.gz')
    path = (Path(state) / relative).resolve()
    if not path.is_relative_to((Path(state) / 'captures').resolve()):
        raise ValueError('Capture outside the archived source directory')
    if path not in cache:
        content = gzip.decompress(path.read_bytes())
        cache[path] = (digest_bytes(content), json.loads(content))
    sha, source = cache[path]
    if sha != forecast['source_snapshot_sha256'][forecast['league']]:
        raise ValueError('Archived pre-match source changed')
    matches = [g for g in source['dates'] if 'understat:' + str(g['id']) == forecast['fixture_id']]
    if len(matches) != 1:
        raise ValueError('Archived event is missing or ambiguous')
    game = matches[0]
    if (game['isResult'] is not False or str(game['h']['id']) != forecast['home_id']
            or str(game['a']['id']) != forecast['away_id']
            or utc(forecast['recorded_at_utc']) >= utc(forecast['kickoff_utc'])
            or forecast.get('schedule_source') != 'sportytrader_jsonld_utc'):
        raise ValueError('Invalid pre-match timezone anchor')
    return game, sha


def normalize_settlement_sources(state, forecasts, sources):
    normalized = copy.deepcopy(sources)
    corrections = []; unresolved = []; cache = {}
    for identity, forecast in forecasts.items():
        matches = [g for g in normalized.get(forecast['league'], {}).get('dates', [])
                   if 'understat:' + str(g['id']) == identity]
        if len(matches) != 1 or matches[0]['isResult'] is not True:
            continue
        game = matches[0]
        try:
            kickoff = utc(forecast['kickoff_utc'])
            initial, sha = archived_game(state, forecast, cache)
            converted, zone = resolve(initial['datetime'], game['datetime'], forecast['kickoff_utc'], forecast['league'])
            corrections.append({'fixture_id': identity, 'timezone': zone,
                'initial_datetime': initial['datetime'], 'observed_datetime': game['datetime'],
                'resolved_utc': converted.isoformat(), 'verified_kickoff_utc': kickoff.isoformat(),
                'prematch_source_sha256': sha,
                'within_original_30min_tolerance': abs((converted-kickoff).total_seconds()) <= 1800})
            game['datetime'] = converted.replace(tzinfo=None).isoformat(sep=' ')
        except (ValueError, KeyError, OSError) as error:
            unresolved.append({'fixture_id': identity, 'reason': str(error)})
    return normalized, {'corrections': corrections, 'unresolved': unresolved}


def settle_normalized(original_settle, journal, sources, metadata, audit):
    blocked = {item['fixture_id'] for item in audit['unresolved']}
    class SettlementJournal:
        def records(self, kind):
            records = journal.records(kind)
            return {key: value for key, value in records.items() if key not in blocked} if kind == 'forecast' else records
        def append(self, *args):
            return journal.append(*args)
    count, issues = original_settle(SettlementJournal(), sources, metadata)
    issues += [{'fixture_id': item['fixture_id'], 'reason': 'settlement_timezone_unresolved',
                'detail': item['reason']} for item in audit['unresolved']]
    return count, issues


def verify_amendment(experiment, registration):
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    if (manifest['version'] != VERSION or manifest['timezone_candidates'] != ZONES
            or manifest['runtime_sha256'] != digest_bytes(Path(__file__).read_bytes())):
        raise ValueError('Settlement amendment changed; register a new version')
    canonical = json.dumps(registration, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if digest_bytes(canonical.encode()) != manifest['source_registration_sha256'][experiment]:
        raise ValueError('Settlement amendment belongs to another experiment')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', choices=['paper_simulation', 'paper_positive15'], required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Live paper settlement runs on GitHub Actions only')
    sys.path.insert(0, str(ROOT / args.experiment))
    collector = importlib.import_module('run_paper')
    registration = collector.check_registration()
    manifest = verify_amendment(args.experiment, registration)
    original_collect, original_settle = collector.collect, collector.settle
    context = {}
    def collect(batch):
        result = original_collect(batch)
        context['batch'] = batch
        return result
    def settle(journal, sources, metadata):
        normalized, audit = normalize_settlement_sources(collector.STATE, journal.records('forecast'), sources)
        audit.update(version=VERSION, runtime_sha256=manifest['runtime_sha256'],
            amendment_sha256=digest_bytes(MANIFEST.read_bytes()),
            source_snapshot_sha256={k: v['sha256'] for k, v in metadata.items()},
            github_run_id=os.environ.get('GITHUB_RUN_ID'))
        collector.write(context['batch'] / 'settlement_runtime.json', audit)
        journal.append('run', VERSION + ':' + context['batch'].name, audit)
        return settle_normalized(original_settle, journal, normalized, metadata, audit)
    collector.collect, collector.settle = collect, settle
    collector.main()


if __name__ == '__main__':
    main()
