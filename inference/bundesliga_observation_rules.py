"""Frozen simulation decision rules copied from the 25 October audit."""
import numpy as np
import pandas as pd
from inference.bundesliga_draw_recalibrated import VERSION

def evaluate(frame,policy,now):
    now=pd.Timestamp(now);issues=[]
    if now.tzinfo is None:raise ValueError('UTC-aware review time required')
    if frame.empty:return dict(status='clore_non_confirmee' if now>=pd.Timestamp(policy['deadline']) else 'pas_de_nouveaux_paris',bets=0,gain=0,pending=0,loss_budget=10,deadline=policy['deadline'])
    f=frame.copy()
    if f.fixture_id.duplicated().any():issues.append('duplicate_fixture')
    for c in ['decision_at_utc','kickoff_utc','quote_observed_at_utc','features_available_at_utc','settled_at_utc','closing_quote_at_utc']:
        original=f[c].astype(str)
        invalid=~original.isin(['','nan'])&~original.str.contains(r'(?:Z|[+-]\d\d:\d\d)$',regex=True)
        if invalid.any():issues.append('naive_timestamp_'+c)
        f[c]=pd.to_datetime(f[c],utc=True,errors='coerce',format='mixed')
    required_times=['decision_at_utc','kickoff_utc','quote_observed_at_utc','features_available_at_utc']
    if f[required_times].isna().any().any():issues.append('missing_timestamp')
    if not ((f.decision_at_utc>=pd.Timestamp(policy['start']))&(f.decision_at_utc<f.kickoff_utc)&(f.quote_observed_at_utc<=f.decision_at_utc)&(f.features_available_at_utc<=f.decision_at_utc)&(f.decision_at_utc<=now)).all():issues.append('noncausal_or_wrong_cohort')
    if not (f.filter_version.eq(VERSION)&f.model_primary_sha256.isin(policy['primary_hashes'])&f.model_secondary_sha256.isin(policy['secondary_hashes'])).all():issues.append('wrong_model_or_filter')
    bookmaker=f.bookmaker.fillna('').astype(str).str.strip().str.lower()
    if not (f.price_type.eq('executable')&bookmaker.ne('')&~bookmaker.isin(['avg','average','moyenne'])).all():issues.append('unverified_price')
    nums=['p_primary_draw','p_binary_draw','odds_away','odds_draw','odds_home','stake_units','profit_units','closing_odds_away','closing_odds_draw','closing_odds_home']
    for c in nums:f[c]=pd.to_numeric(f[c],errors='coerce')
    selected=f.selected.astype(str).str.lower().isin(['1','true']);f['is_selected']=selected
    if not f.selected.astype(str).str.lower().isin(['1','0','true','false']).all():issues.append('invalid_selection')
    prices=f[['odds_away','odds_draw','odds_home']].to_numpy(float);p=f[['p_primary_draw','p_binary_draw']].min(axis=1)
    if not np.isfinite(prices).all() or not (prices>1).all():issues.append('invalid_odds')
    if not f[['p_primary_draw','p_binary_draw']].apply(lambda x:x.between(0,1)).all().all():issues.append('invalid_probability')
    q=1/prices;q=q/q.sum(axis=1,keepdims=True)
    eligible=(p*f.odds_draw*.98-1>.15)&(p-q[:,1]>=.04)&f.odds_draw.ge(2.2)&f.odds_draw.lt(10)&(q.argmax(axis=1)!=1)
    if (selected&~eligible).any():issues.append('selected_outside_frozen_rule')
    if (~selected&f.abstention_reason.fillna('').eq('')).any():issues.append('unlogged_abstention')
    if not f.stake_units.eq(selected.astype(int)).all():issues.append('wrong_stake')
    if not f.result_status.isin(['pending','won','lost','void','abstained']).all():issues.append('invalid_result_status')
    if (selected&f.result_status.eq('abstained')).any() or (~selected&~f.result_status.eq('abstained')).any():issues.append('selection_result_conflict')
    settled=selected&f.result_status.isin(['won','lost','void']);pending=selected&f.result_status.eq('pending')
    if not ((f.loc[settled,'settled_at_utc']>=f.loc[settled,'kickoff_utc'])&(f.loc[settled,'settled_at_utc']<=now)).all():issues.append('invalid_settlement_time')
    expected=np.where(f.result_status.eq('won'),f.odds_draw-1,np.where(f.result_status.eq('lost'),-1,0))
    if not np.allclose(f.loc[settled,'profit_units'],expected[settled]):issues.append('incorrect_profit')
    if issues:return dict(status='suspendre_integrite',issues=sorted(set(issues)),action='No new simulated bets; investigate, preserve originals, do not silently backfill.')
    s=f[settled].sort_values(['settled_at_utc','fixture_id']);gain=float(s.profit_units.sum());equity=s.profit_units.cumsum()
    result=dict(bets=int(selected.sum()),settled=len(s),pending=int(pending.sum()),gain=gain,
                worst_case_after_pending=gain-int(pending.sum()),max_drawdown=float((np.maximum.accumulate(np.r_[0,equity])-np.r_[0,equity]).max()))
    if (equity<=-10).any():return dict(**result,status='abandon_budget',reason='The -10u loss budget was reached; no reset after a recovery.')
    if gain-int(pending.sum())<=-10:return dict(**result,status='suspendre_exposition',reason='Pending stakes exhaust the remaining 10u loss budget.')
    first=f[selected].sort_values(['decision_at_utc','fixture_id']).head(100)
    deadline=now>=pd.Timestamp(policy['deadline'])
    if len(first)>=100 and first.result_status.eq('pending').any():return dict(**result,status='attendre_reglement_cohorte',reason='No new bets after the first 100 accepted; wait for settlement.')
    if len(first)>=100 or deadline:
        t=first[first.result_status.isin(['won','lost'])].copy()
        if len(t)<100:return dict(**result,status='clore_non_confirmee',reason='Deadline or 100 accepted reached without 100 nonvoid settled bets; insufficient evidence.')
        t['stress']=np.where(t.result_status.eq('won'),t.odds_draw*.98-1,-1)
        stress=float(t.stress.sum());t['week']=t.kickoff_utc.dt.strftime('%Y-%W')
        a=t.groupby('week').stress.sum().to_numpy();rng=np.random.default_rng(20261026)
        sims=a[rng.integers(len(a),size=(20000,len(a)))].sum(axis=1);lo,hi=np.quantile(sims,[.05,.95])
        closecols=['closing_odds_away','closing_odds_draw','closing_odds_home'];valid=t[closecols].gt(1).all(axis=1)&t.closing_quote_at_utc.le(t.kickoff_utc)&t.closing_quote_at_utc.ge(t.decision_at_utc)
        clv=float((t.loc[valid,'odds_draw']/t.loc[valid,'closing_odds_draw']-1).mean()) if valid.any() else None
        season=t.kickoff_utc.dt.year-(t.kickoff_utc.dt.month<7).astype(int);season_ok=int((season.value_counts()>=25).sum())>=2
        result.update(stressed_gain=stress,stress_gain_lower95=float(lo),stress_gain_upper95=float(hi),closing_coverage=float(valid.mean()),mean_clv=clv)
        if stress<=0 or hi<=0:return dict(**result,status='abandon_resultat',reason='Final frozen endpoint does not meet the economic return requirement; not proof of permanent unprofitability.')
        passes=lo>0 and season_ok and t.profit_units.sum()-t.profit_units.max()>0 and valid.mean()>=.8 and clv is not None and clv>0
        return dict(**result,status='examen_confirmation' if passes else 'clore_non_confirmee',reason='No automatic public promotion. Review data quality and approximate inference assumptions.')
    return dict(**result,status='continuer_simulation',review50_due=len(s)>=50)
