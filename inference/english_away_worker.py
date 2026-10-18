"""Isolated inference using the unchanged, hash-verified paper feature adapter."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'paper_simulation'))
from run_paper import check_registration, identify_candidates
from paper_models import Models, current_history, frame_for_fixture


def main():
    import numpy as np
    import pandas as pd
    import requests
    from threadpoolctl import threadpool_limits
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    registration = check_registration()
    import sklearn, xgboost
    for module in [np, pd, sklearn, xgboost]:
        if module.__version__ != registration['runtime'][module.__name__]:
            raise ValueError('English frozen model runtime changed: ' + module.__name__)
    output = Path(args.output)
    capture = output.parent / datetime.now(timezone.utc).strftime('capture-%Y%m%dT%H%M%S%fZ')
    capture.mkdir(parents=True)
    def fetch(job):
        name, url = job
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (ScorePredict)',
                                               'X-Requested-With': 'XMLHttpRequest'}, timeout=40)
        response.raise_for_status()
        content = response.content
        (capture / (name + '.gz')).write_bytes(gzip.compress(content, mtime=0))
        value = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig')))) if name == 'fixtures' else response.json()
        return name, value, {'url': url, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                             'sha256': hashlib.sha256(content).hexdigest()}
    with ThreadPoolExecutor(max_workers=2) as pool:
        fetched = list(pool.map(fetch, [('fixtures', 'https://www.football-data.co.uk/fixtures.csv'),
            ('EPL', 'https://understat.com/getLeagueData/EPL/2026')]))
    sources = {name: value for name, value, _ in fetched}
    metadata = {name: meta for name, _, meta in fetched}
    sources['fixtures'] = [r for r in sources['fixtures'] if r.get('Div') == 'E0']
    candidates, rejected = identify_candidates(sources, Path(args.catalog))
    rows = []; audits = []
    if candidates:
        raw = current_history({'EPL': sources['EPL']})
        models = Models()
        for fixture in candidates:
            now = pd.Timestamp.now(tz='UTC')
            if now - pd.Timestamp(metadata['fixtures']['retrieved_at_utc']) > pd.Timedelta(minutes=30):
                raise ValueError('English quote capture expired')
            frame, audit = frame_for_fixture(raw, fixture, fixture['quotes'], now)
            with threadpool_limits(limits=2):
                p, vectors = models.score(frame, ['logit_sports'])
            away, draw, home = map(float, p['logit_sports'][0])
            odds = fixture['quotes']['B365']['away']
            selected = 2 <= odds <= 6 and away * odds * .98 - 1 > .10
            market = (1 / odds) / sum(1 / v for v in fixture['quotes']['B365'].values())
            row = dict(fixture_id=fixture['production_fixture_id'], kickoff_utc=fixture['kickoff_utc'],
                league='EPL', team_name=fixture['home_team'], opponent_name=fixture['away_team'],
                strategy_name='epl_away_logit_strict_2026_10_18', train_league='ALL', bet_league='EPL',
                selected_outcome='away_win', selected_odds=odds, predicted_probability=away,
                raw_model_probability=away, pred_home_win=home, pred_draw=draw, pred_away_win=away,
                market_home_win_odds_open=fixture['quotes']['B365']['home'],
                market_draw_odds_open=fixture['quotes']['B365']['draw'], market_away_win_odds_open=odds,
                market_probability=market, edge=away-market, value_score=away/market,
                expected_value=away*odds*.98-1, raw_expected_value=away*odds-1,
                probability_note='frozen_logit_sports_through_2024__sporting_cutoff_72h__B365__ev10_haircut2',
                train_max_season=2024, bet_is_market_favorite=odds==min(fixture['quotes']['B365'].values()),
                recommended_bet='away_win' if selected else '')
            rows.append(row)
            audits.append(dict(fixture=fixture, history=audit, probabilities=dict(away=away, draw=draw, home=home),
                recorded_at_utc=now.isoformat(), selected=selected,
                features=json.loads(vectors['logit_sports'].to_json(orient='records'))[0]))
    pd.DataFrame(rows, columns=list(rows[0]) if rows else ['fixture_id']).to_csv(output, index=False)
    (capture / 'audit.json').write_text(json.dumps(dict(sources=metadata, forecasts=audits, rejected=rejected,
        model_sha256=registration['frozen_sha256']['frozen/models/sports_and_control.pkl']),
        ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print({'english_fixtures_scored': len(rows), 'english_recommendations': sum(bool(r['recommended_bet']) for r in rows)})


if __name__ == '__main__':
    main()
