"""Private persistent receipts, separate from the public prediction portfolio.

The Supabase recommended flag means 'persist this private observation', including
abstentions. Actual virtual enrollment is receipt.selected, never this DB flag.
Unverifiable prices are diagnostic observations, excluded from confirmation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import pandas as pd
from inference.bundesliga_draw_recalibrated import apply_filter, VERSION
from inference.bundesliga_observation_rules import evaluate

ROOT=Path(__file__).resolve().parents[1]
PORTFOLIO='private_bundesliga_recalibrated_2026_10_26'
STATE=ROOT/'inference/output/bundesliga_observation'
LEDGER=STATE/'ledger.csv';STATUS=STATE/'store_status.json';REPORT=STATE/'report.json'
REGISTRATION=Path(__file__).with_name('bundesliga_observation_registration.json')
TERMINAL={'won','lost','void'}

def policy():
    p=json.loads(REGISTRATION.read_text(encoding='utf8'))
    for name,digest in p['frozen_files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Private Bundesliga frozen file changed: '+name)
    return p

def rows():
    from inference.live_tracking import TRACKING_COLUMNS
    return pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame(columns=TRACKING_COLUMNS)

def receipt(row):
    r=json.loads(row['probability_note'])
    if r['portfolio']!=PORTFOLIO:raise ValueError('Wrong private receipt portfolio')
    return r

def confirmation_frame(frame):
    records=[]
    for r in frame.to_dict('records'):
        meta=receipt(r)
        if not meta['evidence_verified']:continue
        d=meta['decision'].copy()
        if not d['selected']:
            d.update(result_status='abstained',profit_units=0.,settled_at_utc='')
        else:
            status=r['result_status'];d['result_status']=status if status in TERMINAL else 'pending'
            d['settled_at_utc']=meta.get('settled_at_utc','')
            d['profit_units']=float(r['selected_odds'])-1 if status=='won' else (-1. if status=='lost' else (0. if status=='void' else None))
        records.append(d)
    return pd.DataFrame(records)

def state(frame,p,now):
    data=confirmation_frame(frame)
    status=evaluate(data,p,now)
    accepted=int(data.selected.astype(bool).sum()) if not data.empty else 0
    if accepted>=p['max_new_bets'] and status['status']=='continuer_simulation':
        status['status']='attendre_reglement_cohorte'
    return status

def record_forecasts(scored,now=None):
    from inference.live_tracking import build_tracking_rows,append_tracking_rows
    now=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    p=policy();STATE.mkdir(parents=True,exist_ok=True)
    existing=rows()
    if now<pd.Timestamp(p['start']) or scored.empty or 'league' not in scored:
        export_report(now=now);return
    private=apply_filter(scored[scored.league.eq('Bundesliga')&scored.selected_outcome.eq('draw')])
    if private.empty:export_report(now=now);return
    private['_eligible']=private.recommended_bet.fillna('').eq('draw')
    private=private.sort_values(['fixture_id','_eligible','strategy_name'],ascending=[True,False,True]).drop_duplicates('fixture_id')
    seen=set(existing.fixture_id.dropna().astype(str)) if 'fixture_id' in existing else set()
    accepted_rows=[]
    for raw in private.to_dict('records'):
        fixture=str(raw['fixture_id']);kickoff=pd.to_datetime(raw.get('kickoff_utc'),utc=True,errors='coerce')
        if fixture in seen or pd.isna(kickoff) or kickoff<=now:continue
        if now>=pd.Timestamp(p['deadline']):break
        d=dict(fixture_id=fixture,decision_at_utc=now.isoformat(),kickoff_utc=kickoff.isoformat(),
          quote_observed_at_utc=raw.get('quote_observed_at_utc',''),features_available_at_utc=raw.get('features_available_at_utc',''),
          bookmaker=raw.get('bookmaker',''),price_type=raw.get('price_type','unverified'),filter_version=VERSION,
          model_primary_sha256=p['primary_hashes'][0],model_secondary_sha256=p['secondary_hashes'][0],
          p_primary_draw=raw.get('multiclass_draw_probability'),p_binary_draw=raw.get('binary_draw_probability'),
          odds_away=raw.get('market_away_win_odds_open'),odds_draw=raw['selected_odds'],odds_home=raw.get('market_home_win_odds_open'),
          selected=0,abstention_reason='filter_rejected',stake_units=0,result_status='abstained',settled_at_utc='',profit_units=0.,
          closing_quote_at_utc='',closing_odds_away=None,closing_odds_draw=None,closing_odds_home=None)
        d={k:(None if isinstance(v,float) and not math.isfinite(v) else v) for k,v in d.items()}
        verified=evaluate(pd.DataFrame([d]),p,now)['status']!='suspendre_integrite'
        current=state(existing,p,now)
        count=sum(receipt(r)['decision']['selected'] for r in existing.to_dict('records'))
        permitted=current['status'] in {'continuer_simulation','pas_de_nouveaux_paris'} and count<100
        # Reserve the whole next stake before admitting it.
        available=current.get('worst_case_after_pending',0)-1>=-10
        if raw['_eligible'] and verified and permitted and available:
            d.update(selected=1,stake_units=1,abstention_reason='',result_status='pending',profit_units=None)
        elif not verified:d['abstention_reason']='price_or_feature_provenance_unverified'
        elif raw['_eligible']:d['abstention_reason']='monitor_stop_or_exposure_limit'
        meta=dict(portfolio=PORTFOLIO,captured_at_utc=now.isoformat(),qualified_by_filter=bool(raw['_eligible']),
                  evidence_verified=bool(verified),decision=d,source_strategy=str(raw['strategy_name']),settled_at_utc='')
        row=dict(raw,strategy_name=PORTFOLIO,strategy_names=PORTFOLIO,recommended_bet='draw',stake_eur=0.,
                 probability_note=json.dumps(meta,ensure_ascii=False,allow_nan=False))
        tracked=build_tracking_rows(pd.DataFrame([row]),portfolio_name=PORTFOLIO)
        tracked['prediction_generated_at_utc']=now.isoformat()
        append_tracking_rows(tracked,LEDGER)
        existing=rows();seen.add(fixture);accepted_rows.append(tracked)
    export_report(now=now)

def export_report(now=None):
    now=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    p=policy();frame=rows();status=state(frame,p,now)
    captures=[receipt(r) for r in frame.to_dict('records')]
    qualified=[r for r in frame.to_dict('records') if receipt(r)['qualified_by_filter']]
    settled=[r for r in qualified if r['result_status'] in {'won','lost'}]
    theoretical=sum(float(r['selected_odds'])-1 if r['result_status']=='won' else -1 for r in settled)
    report=dict(private=True,portfolio=PORTFOLIO,updatedAt=now.isoformat(),rules=p,monitor=status,
                observations=len(frame),unverified_observations=sum(not r['evidence_verified'] for r in captures),
                diagnostics=dict(qualified_forecasts=len(qualified),settled_forecasts=len(settled),hypothetical_gain_at_displayed_prices=theoretical,
                                 note='Diagnostic only; unverified prices do not enter the stopped-budget confirmation cohort.'),
                decision_receipts=captures,ledger=frame.astype(object).where(frame.notna(),None).to_dict('records'),
                note='Private diagnostics are not public bets. Only pre-match verified executable prices enter the confirmation cohort; no retrospective enrollment.')
    STATE.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf8')
    return report

def persist():
    from inference.supabase_prediction_store import push
    return push(LEDGER,STATUS,portfolio_name=PORTFOLIO)

def settle(now=None):
    from inference.result_monitor import collect_results_for_due_rows,settle_due_predictions
    from inference.live_tracking import refresh_pending_fixture_dates_from_catalog
    now=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    frame=rows()
    if frame.empty:export_report(now);return
    local_now=now.tz_convert('Europe/Paris').tz_localize(None)
    results,_=collect_results_for_due_rows(frame,now=local_now,minimum_elapsed_minutes=105,portfolio_name=PORTFOLIO,timeout_seconds=30)
    updated,_=refresh_pending_fixture_dates_from_catalog(frame,results)
    updated,_=settle_due_predictions(updated,results,now=local_now,minimum_elapsed_minutes=105,portfolio_name=PORTFOLIO)
    for idx,r in updated.iterrows():
        meta=receipt(r)
        if r['result_status'] in TERMINAL and not meta.get('settled_at_utc'):
            meta['settled_at_utc']=now.isoformat()
            updated.at[idx,'probability_note']=json.dumps(meta,ensure_ascii=False,allow_nan=False)
    updated.to_csv(LEDGER,index=False);export_report(now)

def main():
    from inference.supabase_prediction_store import pull,push
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['pull','settle-push','report']);args=parser.parse_args()
    policy();STATE.mkdir(parents=True,exist_ok=True)
    if args.action=='pull':
        pull(LEDGER,STATUS,portfolio_name=PORTFOLIO);export_report()
    elif args.action=='settle-push':
        settle();persist()
    else:export_report()
    print('Private Bundesliga observation:',args.action,'completed; public ledger untouched.')

if __name__=='__main__':main()
