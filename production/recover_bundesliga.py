"""Explicit one-off recovery from an authentic archive, checked against current results."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'production/recovery/bundesliga-2026-11-01.json'
ARCHIVE_SHA256 = 'a0550893f3225d5d4e32a34a21faab0484f8f835548668f61c58b619daa06646'
ARCHIVE_RUN = 'https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/runs/41351587088'


def verify_coverage(payload, results, now):
    from data_pipeline.market_data import normalize_team_name as norm
    def key(date, home, away):
        return str(date)[:10], norm(home), norm(away)
    cached = {key(g['datetime'], g['h']['title'], g['a']['title']): g
              for g in payload['dates'] if g['isResult'] is True}
    current = {}
    for row in results:
        if row.get('FTHG', '') == '' or row.get('FTAG', '') == '':
            continue
        day = datetime.strptime(row['Date'], '%d/%m/%Y').date()
        identity = key(day, row['HomeTeam'], row['AwayTeam'])
        if identity in current:
            raise ValueError('Duplicate current result')
        current[identity] = row
    if not current or set(cached) != set(current):
        raise ValueError(f'Archive incomplete: {len(cached)} cached / {len(current)} current results; '
                         f'missing={sorted(set(current)-set(cached))}')
    for k, row in current.items():
        if (int(row['FTHG']), int(row['FTAG'])) != (int(cached[k]['goals']['h']), int(cached[k]['goals']['a'])):
            raise ValueError('Archived/current result disagreement: ' + str(k))
    # A periodic CSV can lag. Refuse an old pending match even if the CSV has
    # not yet added it; never infer that an unchanged CSV proves freshness.
    for game in payload['dates']:
        kickoff = datetime.fromisoformat(game['datetime']).replace(tzinfo=timezone.utc)
        if game['isResult'] is False and (now - kickoff).total_seconds() > 150 * 60:
            raise ValueError('Scheduled match now due but absent from archived history: ' + str(game['id']))
    return len(current)


def read_archive():
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Recovery archive changed')
    return json.loads(ARCHIVE.read_text(encoding='utf8'))


def score(catalog, output):
    import pandas as pd
    import requests
    from data_pipeline.scrapper import normalize_understat_teams, extract_stats_from_data, update_stats_with_opponents
    from data_pipeline.audit_club_coverage import audit_league, audit_upcoming
    from inference.upcoming_portfolio_strategy import (load_historical_team_rows, prepare_fixture_frame,
        build_dataset_with_fixtures, score_strategy_rows)
    from inference.pooled_release import load_release_models
    from inference.portfolio_presets import PORTFOLIO_PRESETS, DEFAULT_PORTFOLIO_NAME
    from inference.bundesliga_draw_public import apply_filter
    payload = read_archive()
    output.parent.mkdir(parents=True, exist_ok=True)
    url = 'https://www.football-data.co.uk/mmz4281/2627/D1.csv'
    response = requests.get(url, timeout=30); response.raise_for_status()
    (output.parent / 'current_D1.csv').write_bytes(response.content)
    results = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    now = datetime.now(timezone.utc)
    count = verify_coverage(payload, results, now)
    data = {'Bundesliga 2026': normalize_understat_teams(payload)}
    stats = update_stats_with_opponents(extract_stats_from_data(data), data)
    fresh = pd.DataFrame([r for rows in stats.values() for r in rows])
    registry = pd.DataFrame([dict(league='Bundesliga', season=2026, team_id=k, team_name=t['title'])
                             for k, t in data['Bundesliga 2026'].items()])
    integrity = audit_league(payload, registry.to_dict('records'), fresh.to_dict('records'),
                            league='Bundesliga', season=2026, expected_count=18)
    if integrity['errors']:
        raise ValueError('Incomplete sporting fields: ' + str(integrity['errors']))
    fresh['date'] = pd.to_datetime(fresh.date)
    fresh['league'] = 'Bundesliga'; fresh['season'] = 2026; fresh['season_key'] = 'Bundesliga 2026'
    historical = load_historical_team_rows(str(ROOT / 'Data'))
    historical = historical[historical.league.eq('Bundesliga') & historical.season.lt(2026)]
    raw = pd.concat([historical, fresh], ignore_index=True)
    fixtures = pd.read_csv(catalog)
    fixtures = fixtures[fixtures.league.eq('Bundesliga')].copy()
    kickoff = pd.to_datetime(fixtures.kickoff_utc, utc=True)
    fixtures = fixtures[(kickoff >= pd.Timestamp(now) + pd.Timedelta(minutes=5)) &
                        (kickoff <= pd.Timestamp(now) + pd.Timedelta(hours=24))]
    fixtures['date'] = pd.to_datetime(fixtures.kickoff_utc, utc=True).dt.tz_convert('Europe/Paris').dt.tz_localize(None)
    fixtures = prepare_fixture_frame(fixtures).reset_index(drop=True)
    strategies = PORTFOLIO_PRESETS[DEFAULT_PORTFOLIO_NAME]
    bundles, _ = load_release_models(strategies, train_max_season=2024)
    if fixtures.empty:
        scored = pd.DataFrame(columns=['fixture_id'])
    else:
        dataset, ids = build_dataset_with_fixtures(raw, fixtures, registry)
        future = dataset[dataset.match_id.isin(ids)].copy()
        for col in ['fixture_id', 'kickoff_utc']:
            future[col] = future.match_id.map(dict(zip(ids, fixtures[col])))
        audit_upcoming(raw, future, bundles, output.parent / 'inputs_audit.json')
        scored = apply_filter(score_strategy_rows(future, bundles, [s for s in strategies if s.bet_league == 'Bundesliga']))
    scored.to_csv(output, index=False)
    report = dict(archiveRun=ARCHIVE_RUN, archiveSha256=ARCHIVE_SHA256,
                  originalCapturedAt=payload['captured_at'], completenessCheckedAt=now.isoformat(),
                  resultsSource=url, resultsSha256=hashlib.sha256(response.content).hexdigest(),
                  completedMatches=count, sportingFieldsAudit=integrity,
                  scoredFixtures=len(fixtures), mode='explicit_verified_archive')
    (output.parent / 'recovery_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    xgb_path = output.with_name('recovered_xgb.csv')
    env = os.environ.copy(); env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
    subprocess.run([sys.executable, str(Path(__file__)), '--xgb-only', '--catalog', str(catalog.resolve()),
                    '--output', str(xgb_path.resolve())], cwd=ROOT, env=env, check=True, timeout=300)
    xgb = pd.read_csv(xgb_path)
    if not xgb.empty:
        xgb['date'] = pd.to_datetime(xgb.kickoff_utc, utc=True).dt.tz_convert('Europe/Paris').dt.tz_localize(None)
        scored = pd.concat([scored, xgb], ignore_index=True)
    scored.to_csv(output, index=False)
    print({'recovered_bundesliga_matches': count, 'strategy_rows': len(scored),
           'selected_before_deduplication': int(scored.recommended_bet.fillna('').ne('').sum()) if not scored.empty else 0})


def score_xgb(catalog, output):
    # Same isolated frozen adapter/import order as public_additions_worker.
    sys.path[:0] = [str(ROOT / 'paper_positive15'), str(ROOT)]
    from run_paper import check_registration, identify_candidates
    from paper_models import Models, six
    import numpy as np
    import pandas as pd
    import requests, sklearn, xgboost
    from inference.public_additions import BUNDESLIGA, qualifies
    registration = check_registration()
    for module in [np, pd, sklearn, xgboost]:
        if module.__version__ != registration['runtime'][module.__name__]:
            raise ValueError('Frozen runtime changed')
    payload = read_archive()
    response = requests.get('https://www.football-data.co.uk/fixtures.csv', timeout=30); response.raise_for_status()
    (output.parent / 'current_fixtures.csv').write_bytes(response.content)
    quotes = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    candidates, rejected = identify_candidates({'Bundesliga': payload, 'fixtures': [q for q in quotes if q.get('Div') == 'D1']}, catalog)
    models = Models(); rows = []; audits = []
    if candidates:
        raw = six.current_history({'Bundesliga': payload})
        for fixture in candidates:
            now = pd.Timestamp.now(tz='UTC')
            frame, audit = six.frame_for_fixture(raw, fixture, fixture['quotes'], now)
            probs, vectors = models.score(frame, ['native_mean'])
            away, draw, home = map(float, probs['native_mean'][0])
            q = fixture['quotes']['B365']; odds = q['draw']; market = (1 / odds) / sum(1 / v for v in q.values())
            rows.append(dict(fixture_id=fixture['production_fixture_id'], kickoff_utc=fixture['kickoff_utc'], league='Bundesliga',
                team_name=fixture['home_team'], opponent_name=fixture['away_team'], strategy_name=BUNDESLIGA,
                selected_outcome='draw', selected_odds=odds, predicted_probability=draw, raw_model_probability=draw,
                pred_home_win=home, pred_draw=draw, pred_away_win=away, market_probability=market,
                market_home_win_odds_open=q['home'], market_draw_odds_open=odds, market_away_win_odds_open=q['away'],
                edge=draw-market, value_score=draw/market, expected_value=draw*odds*.98-1,
                raw_expected_value=draw*odds-1, train_max_season=2024,
                probability_note='frozen_native_mean_through2024__72h__B365__ev2_haircut2__verified_archive_20261101',
                recommended_bet='draw' if qualifies(draw, odds) else ''))
            audits.append(dict(fixture=fixture, history=audit, features=json.loads(vectors['native_mean'].to_json(orient='records')),
                               probabilities=dict(away=away, draw=draw, home=home), recordedAt=now.isoformat()))
    pd.DataFrame(rows, columns=list(rows[0]) if rows else ['fixture_id']).to_csv(output, index=False)
    (output.parent / 'recovered_xgb_audit.json').write_text(json.dumps(dict(rejected=rejected, forecasts=audits,
        archiveCapturedAt=payload['captured_at'], archiveSha256=ARCHIVE_SHA256), ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--xgb-only', action='store_true')
    args = parser.parse_args()
    (score_xgb if args.xgb_only else score)(args.catalog, args.output)
