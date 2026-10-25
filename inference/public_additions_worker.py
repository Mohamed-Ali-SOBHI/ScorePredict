"""Isolated scoring of the two promoted, hash-verified frozen observation models."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse,csv,gzip,hashlib,io,json,sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'paper_positive15'), str(ROOT)]
from run_paper import check_registration, identify_candidates
from paper_models import Models, six
from inference.public_additions import STRATEGIES, ACTIVATED_AT, qualifies


def main():
    import numpy as np
    import pandas as pd
    import requests,sklearn,xgboost
    from threadpoolctl import threadpool_limits
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();registration=check_registration()
    for module in [np,pd,sklearn,xgboost]:
        if module.__version__ != registration['runtime'][module.__name__]:
            raise ValueError('Frozen addition runtime changed: '+module.__name__)
    output=Path(args.output);capture=output.parent/datetime.now(timezone.utc).strftime('capture-%Y%m%dT%H%M%S%fZ');capture.mkdir(parents=True)
    def fetch(job):
        name,url=job;r=requests.get(url,headers={'User-Agent':'Mozilla/5.0 (ScorePredict)','X-Requested-With':'XMLHttpRequest'},timeout=40);r.raise_for_status()
        (capture/(name+'.gz')).write_bytes(gzip.compress(r.content,mtime=0))
        value=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig')))) if name=='fixtures' else r.json()
        return name,value,dict(url=url,retrieved_at_utc=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(r.content).hexdigest())
    jobs=[('fixtures','https://www.football-data.co.uk/fixtures.csv')]+[(league,f'https://understat.com/getLeagueData/{league}/2026') for league in ['Bundesliga','EPL']]
    with ThreadPoolExecutor(max_workers=3) as pool:items=list(pool.map(fetch,jobs))
    sources={name:value for name,value,_ in items};metadata={name:meta for name,_,meta in items}
    sources['fixtures']=[r for r in sources['fixtures'] if r.get('Div') in {'D1','E0'}]
    candidates,rejected=identify_candidates(sources,Path(args.catalog));rows=[];audits=[]
    if candidates:
        raw=six.current_history({league:sources[league] for league in ['Bundesliga','EPL']});models=Models()
        for fixture in candidates:
            now=pd.Timestamp.now(tz='UTC')
            if now<pd.Timestamp(ACTIVATED_AT):raise ValueError('Additions not yet activated')
            if now-pd.Timestamp(metadata['fixtures']['retrieved_at_utc'])>pd.Timedelta(minutes=30):raise ValueError('Addition quote capture expired')
            frame,audit=six.frame_for_fixture(raw,fixture,fixture['quotes'],now)
            identity,spec=next((k,v) for k,v in STRATEGIES.items() if v['league']==fixture['league'])
            with threadpool_limits(limits=2):probs,vectors=models.score(frame,[spec['model']])
            away,draw,home=map(float,probs[spec['model']][0]);o='draw' if spec['outcome']=='draw' else 'home'
            probability={'away':away,'draw':draw,'home':home}[o];quotes=fixture['quotes']['B365'];odds=quotes[o]
            market=(1/odds)/sum(1/v for v in quotes.values());selected=qualifies(probability,odds)
            rows.append(dict(fixture_id=fixture['production_fixture_id'],kickoff_utc=fixture['kickoff_utc'],league=fixture['league'],
                team_name=fixture['home_team'],opponent_name=fixture['away_team'],strategy_name=identity,train_league=fixture['league'],bet_league=fixture['league'],
                selected_outcome=spec['outcome'],selected_odds=odds,predicted_probability=probability,raw_model_probability=probability,
                pred_home_win=home,pred_draw=draw,pred_away_win=away,
                market_home_win_odds_open=quotes['home'],market_draw_odds_open=quotes['draw'],market_away_win_odds_open=quotes['away'],
                market_probability=market,edge=probability-market,value_score=probability/market,
                expected_value=probability*odds*.98-1,raw_expected_value=probability*odds-1,
                probability_note='frozen_'+spec['model']+'_through2024__72h__B365__ev2_haircut2',train_max_season=2024,
                bet_is_market_favorite=odds==min(quotes.values()),recommended_bet=spec['outcome'] if selected else ''))
            audits.append(dict(fixture=fixture,history=audit,strategy=identity,recorded_at_utc=now.isoformat(),selected=selected,
                               probabilities=dict(away=away,draw=draw,home=home),features=json.loads(vectors[spec['model']].to_json(orient='records'))[0]))
    pd.DataFrame(rows,columns=list(rows[0]) if rows else ['fixture_id']).to_csv(output,index=False)
    (capture/'audit.json').write_text(json.dumps(dict(sources=metadata,forecasts=audits,rejected=rejected,
        registration_sha256=hashlib.sha256((ROOT/'paper_positive15/registration.json').read_bytes()).hexdigest()),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print({'addition_fixtures_scored':len(rows),'addition_recommendations':sum(bool(r['recommended_bet']) for r in rows)})


if __name__=='__main__':main()
