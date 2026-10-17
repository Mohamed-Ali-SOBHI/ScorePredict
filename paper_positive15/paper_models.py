"""Inference only: exact archived models used in the 15-strategy report."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sport_features import historical_features

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('six_frozen_adapter',ROOT.parent/'paper_simulation/paper_models.py')
six=importlib.util.module_from_spec(spec);spec.loader.exec_module(six)
normalize_team_name=six.normalize_team_name
OUTCOMES=six.OUTCOMES
RAW=None


def current_history(sources):
    global RAW
    RAW=six.current_history(sources).sort_values(['date','match_id','team_id']).reset_index(drop=True)
    data={league+' 2026':six.normalize_understat_teams(payload) for league,payload in sources.items()}
    stats=six.update_stats_with_opponents(six.extract_stats_from_data(data),data)
    fresh=pd.concat([pd.DataFrame(v) for v in stats.values()],ignore_index=True)
    fresh['team_id']=fresh.team_id.astype(str)
    # The older six-strategy cache omitted non-penalty xG. Preserve these new
    # inputs directly from the captured Understat payload, without imputation.
    for col in ['team_npxG','opponent_npxG','team_xpts','team_goals','opponent_goals']:
        if col not in RAW:
            lookup=fresh.set_index(['match_id','team_id'])[col]
            RAW[col]=lookup.reindex(pd.MultiIndex.from_frame(RAW[['match_id','team_id']])).to_numpy()
    return RAW


def frame_for_fixture(raw,fixture,quotes,decision_time):
    frame,audit=six.frame_for_fixture(raw,fixture,quotes,decision_time)
    return add_sports(frame,raw),audit


def add_sports(frame,raw):
    frame=frame.copy()
    # Both IDs and history order match the frozen research function.
    raw=raw.sort_values(['date','match_id','team_id']).reset_index(drop=True).copy()
    previous=pd.read_csv(ROOT/'sport_history.csv.gz',dtype={'team_id':str})
    previous=previous.set_index(['match_id','team_id'])
    keys=pd.MultiIndex.from_arrays([raw.match_id,raw.team_id.astype(str)])
    for col in ['team_npxG','opponent_npxG','team_shots','opponent_shots','team_xpts','team_goals','opponent_goals']:
        old=previous[col].reindex(keys).to_numpy()
        if col not in raw:raw[col]=old
        else:raw[col]=raw[col].fillna(pd.Series(old,index=raw.index))
    for col in ['team_id','opponent_id']:raw[col]=raw[col].astype(int)
    extra,audit=historical_features(raw,frame)
    for col in extra:frame['new_sport_'+col]=extra[col].to_numpy()
    available=pd.to_datetime(audit.last_result_available,format='mixed')
    cutoff=pd.to_datetime(audit.decision_time,format='mixed')
    if not (available.isna()|(available<=cutoff)).all():raise ValueError('Non-causal supplementary sports')
    return frame


def residual_design(frame):
    frame=frame.copy()
    b=frame[[f'q_B365_pre_{o}' for o in OUTCOMES]].to_numpy(float)
    q=frame[[f'q_Avg_pre_{o}' for o in OUTCOMES]].to_numpy(float)
    missing=(~np.isfinite(q).all(axis=1))|(q<=0).any(axis=1)
    q[missing]=b[missing]
    if not np.isfinite(q).all() or not (q>0).all():raise ValueError('Missing market anchor')
    for j,o in enumerate(OUTCOMES):frame['new_consensus_log_'+o]=np.log(q[:,j]/b[:,j])
    frame['new_consensus_missing']=missing.astype(float)
    for league in ['Bundesliga','EPL','La_liga','Ligue_1']:frame['new_league_'+league]=frame.league.eq(league).astype(float)
    return frame,q


class Models:
    def __init__(self):self.loaded={}

    def ensemble(self,paths,frame,margin=None):
        stack=[];cols=None
        for path in paths:
            path=str(path)
            if path not in self.loaded:
                m=XGBClassifier(n_jobs=1);m.load_model(path);self.loaded[path]=m
            m=self.loaded[path];features=list(m.feature_names_in_)
            if cols is not None and cols!=features:raise ValueError('Inconsistent ensemble features')
            cols=features
            stack.append(m.predict_proba(frame[cols],**({} if margin is None else {'base_margin':np.log(margin)})))
        p=np.asarray(np.mean(stack,axis=0),float)
        p/=p.sum(axis=1,keepdims=True)
        return p,frame[cols]

    def score(self,frame,names):
        if frame.league.nunique()!=1:raise ValueError('One league per prospective receipt required')
        league=frame.league.iloc[0];probabilities={};vectors={}
        for name in names:
            if name=='native_mean':
                bundle=league if league in ['Bundesliga','Serie_A'] else 'EPL'
                paths=[ROOT/'models'/f'native_{bundle}_{seed}.ubj' for seed in [42,73,2026]]
                p,x=self.ensemble(paths,frame)
            elif name.startswith('local_'):
                paths=[ROOT/'models'/f'fold_2026_{league}_{name}_{seed}.ubj' for seed in [42,73,2026]]
                p,x=self.ensemble(paths,frame)
            elif name in ['residual_sport_recency','residual_price']:
                design,q=residual_design(frame)
                paths=[ROOT/'models'/f'{name}_{seed}.ubj' for seed in [42,73,2026]]
                p,x=self.ensemble(paths,design,q)
            else:raise ValueError('Unregistered model family: '+name)
            if not np.isfinite(p).all() or not np.allclose(p.sum(1),1,atol=1e-6):raise ValueError('Invalid forecast')
            probabilities[name]=p;vectors[name]=x
        return probabilities,vectors
