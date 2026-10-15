"""Inference-only adapter for the six frozen research recipes."""
from pathlib import Path
import sys,json,pickle
ROOT=Path(__file__).resolve().parent
FROZEN=ROOT/'frozen'
sys.path[:0]=[str(FROZEN),str(FROZEN/'source'),str(FROZEN/'source/train')]
import numpy as np
import pandas as pd
from scipy.stats import poisson
from data_pipeline.market_data import normalize_team_name
from data_pipeline.scrapper import normalize_understat_teams,extract_stats_from_data,update_stats_with_opponents
from inference.upcoming_portfolio_strategy import prepare_fixture_frame,build_dataset_with_fixtures
from xgboost import XGBClassifier

FEATURES=['elo_rating_gap','elo_win_probability','team_xG_last_5_carry','opponent_xG_last_5_carry',
 'team_xG_against_last_5_carry','opponent_xG_against_last_5_carry','form_score_5_carry','opponent_form_score_5_carry',
 'prev_season_points_per_game_gap','prev_season_xG_gap','prev_season_defensive_gap','team_rest_days','opponent_rest_days',
 'matches_played_in_season_before','opponent_matches_played_in_season_before']
LEAGUES=['Bundesliga','EPL','La_liga','Ligue_1','Serie_A'];OUTCOMES=['away','draw','home']

def design(f):
    x=f[FEATURES].replace([np.inf,-np.inf],np.nan).copy()
    for league in LEAGUES:x['league_'+league]=f.league.eq(league).astype(float)
    return x

def price_features(frame):
    def matrix(prefix):return frame[[f'{prefix}_{o}' for o in OUTCOMES]].to_numpy(float)
    b=matrix('q_B365_pre');a=matrix('q_Avg_pre');f=pd.DataFrame(index=frame.index)
    f['pre_b365_log_away_home']=np.log(b[:,0]/b[:,2]);f['pre_b365_log_draw_home']=np.log(b[:,1]/b[:,2])
    for j,o in enumerate(OUTCOMES):f[f'pre_avg_minus_b365_{o}']=a[:,j]-b[:,j]
    f['pre_b365_overround']=frame.quote_B365_pre_overround;f['pre_avg_overround']=frame.quote_Avg_pre_overround
    books=[]
    for book in ['B365','BW','WH']:
        q=matrix(f'q_{book}_pre');q[~frame[f'has_{book}_pre'].to_numpy(bool)]=np.nan;books.append(q)
    dispersion=np.nanstd(np.stack(books),axis=0)
    for j,o in enumerate(OUTCOMES):f[f'pre_book_std_{o}']=dispersion[:,j]
    f['pre_book_count']=sum(frame[f'has_{book}_pre'].astype(float) for book in ['B365','BW','WH'])
    for book in ['BW','WH']:f[f'pre_has_{book}']=frame[f'has_{book}_pre'].astype(float)
    for league in LEAGUES:f[f'league_{league}']=frame.league.eq(league).astype(float)
    return f

class Models:
    def __init__(self):
        with (FROZEN/'models/sports_and_control.pkl').open('rb') as f:self.sports=pickle.load(f)
        manifest=json.loads((FROZEN/'source/inference/releases/draw_pooled_2026_09_05/manifest.json').read_text(encoding='utf8'))
        self.features=manifest['entries'][0]['models']['primary']['features']
        self.xgb=[]
        for seed in [42,73,2026]:
            model=XGBClassifier(n_jobs=1);model.load_model(FROZEN/f'models/fold_2026_Bundesliga_{seed}_primary.ubj');self.xgb.append(model)
    def score(self,f,names):
        probabilities={};vectors={}
        if {'poisson_sports','logit_sports'}&set(names):x=design(f)
        if 'poisson_sports' in names:
            means=[np.clip(m.predict(x),.05,8) for m in self.sports['poisson_sports']];goals=np.arange(41)
            h=poisson.pmf(goals[None,:],means[0][:,None]);a=poisson.pmf(goals[None,:],means[1][:,None])
            p=np.column_stack([(a*(h.cumsum(axis=1)-h)).sum(axis=1),(h*a).sum(axis=1),(h*(a.cumsum(axis=1)-a)).sum(axis=1)])
            probabilities['poisson_sports']=p/p.sum(axis=1,keepdims=True);vectors['poisson_sports']=x
        if 'logit_sports' in names:
            probabilities['logit_sports']=self.sports['logit_sports'].predict_proba(x);vectors['logit_sports']=x
        if 'outcome_control' in names:
            xprice=price_features(f);q=f[[f'q_B365_pre_{o}' for o in OUTCOMES]].to_numpy(float)
            probabilities['outcome_control']=self.sports['outcome_control'].predict_proba(xprice,q);vectors['outcome_control']=xprice
        if 'original_xgb_ensemble' in names:
            xx=f[self.features];probabilities['original_xgb_ensemble']=np.mean([m.predict_proba(xx) for m in self.xgb],axis=0);vectors['original_xgb_ensemble']=xx
        for p in probabilities.values():
            if not np.isfinite(p).all() or not np.allclose(p.sum(axis=1),1,atol=1e-6):raise ValueError('Invalid model output')
        return probabilities,vectors

def current_history(sources):
    data={league+' 2026':normalize_understat_teams(payload) for league,payload in sources.items()}
    stats=update_stats_with_opponents(extract_stats_from_data(data),data)
    fresh=pd.concat([pd.DataFrame(v) for v in stats.values()],ignore_index=True)
    fresh['date']=pd.to_datetime(fresh.date);fresh=fresh[fresh.result.isin(['w','d','l'])].copy()
    fresh['season_key']=fresh.match_id.str.rsplit('_',n=3).str[0];fresh['league']=fresh.season_key.str.rsplit(' ',n=1).str[0];fresh['season']=2026
    previous=pd.read_pickle(FROZEN/'history_through_previous_season.pkl')
    for c in previous:
        if c not in fresh:fresh[c]=np.nan
    raw=pd.concat([previous[previous.season.lt(2026)],fresh[previous.columns]],ignore_index=True)
    for c in ['team_id','opponent_id']:raw[c]=raw[c].astype(str)
    if raw.duplicated(['match_id','team_id']).any():raise ValueError('Duplicate sporting observation')
    return raw

def frame_for_fixture(raw,fixture,quotes,decision_time):
    kickoff=pd.Timestamp(fixture['kickoff_utc']).tz_convert('UTC')
    cutoff=kickoff-pd.Timedelta(hours=72)
    if cutoff>pd.Timestamp(decision_time):raise ValueError('Sporting cutoff beyond capture')
    history=raw[raw.league.eq(fixture['league'])&(raw.date+pd.Timedelta(hours=2)<=cutoff.tz_localize(None))].copy()
    if history.empty:raise ValueError('No sporting history')
    registry=pd.DataFrame([{'league':fixture['league'],'season':2026,'team_id':fixture['home_id'],'team_name':fixture['home_team']},
                           {'league':fixture['league'],'season':2026,'team_id':fixture['away_id'],'team_name':fixture['away_team']}])
    b=quotes['B365']
    fixture_frame=prepare_fixture_frame(pd.DataFrame([{'date':kickoff.tz_localize(None),'league':fixture['league'],
        'home_team':fixture['home_team'],'away_team':fixture['away_team'],
        'home_win_odds_open':b['home'],'draw_odds_open':b['draw'],'away_win_odds_open':b['away']}]))
    dataset,ids=build_dataset_with_fixtures(history,fixture_frame,registry,decision_time=cutoff,history_timezone='UTC')
    f=dataset[dataset.match_id.isin(ids)].copy().reset_index(drop=True)
    if len(f)!=1:raise ValueError('Unpaired future fixture')
    for book in ['B365','Avg','BW','WH']:
        quote=quotes.get(book);odds=np.array([quote[o] for o in OUTCOMES]) if quote else np.full(3,np.nan)
        inverse=1/odds;q=inverse/inverse.sum();f[f'has_{book}_pre']=quote is not None;f[f'quote_{book}_pre_overround']=inverse.sum()
        for i,o in enumerate(OUTCOMES):f[f'quote_{book}_pre_{o}']=odds[i];f[f'q_{book}_pre_{o}']=q[i]
    return f,{'sporting_cutoff_utc':cutoff.isoformat(),'history_team_rows':len(history),
              'latest_history_kickoff_assumed_utc':history.date.max().isoformat()+'Z'}
