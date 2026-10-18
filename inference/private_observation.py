"""Prospective, private follow-up for the retired Serie A / EPL public rules.

The existing public ledger is never changed by this module. New observations
live in a separate Supabase portfolio; report artifacts must be encrypted.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from inference.publication_policy import PRIVATE_PORTFOLIO,PRIVATE_FREEZE_DATE,PRIVATE_LEAGUES,ACTIVATED_AT

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'inference/output/private_observation'
LEDGER=STATE/'ledger.csv'
STATUS=STATE/'store_status.json'
REPORT=STATE/'report.json'


def record_forecasts(scored):
    import pandas as pd
    from inference.upcoming_portfolio_strategy import dedupe_recommended_bets
    from inference.live_tracking import append_tracking_rows,build_tracking_rows,TRACKING_COLUMNS
    from inference.predict_upcoming_portfolio import write_exports,ALL_EXPORT_COLUMNS
    STATE.mkdir(parents=True,exist_ok=True)
    if not LEDGER.exists():pd.DataFrame(columns=TRACKING_COLUMNS).to_csv(LEDGER,index=False)
    private=(scored.loc[scored.league.isin(PRIVATE_LEAGUES)].copy() if 'league' in scored
             else scored.reindex(columns=ALL_EXPORT_COLUMNS).copy())
    bets=dedupe_recommended_bets(private)
    # These are virtual observations. They never become a real-money order.
    bets['stake_eur']=0.0
    private['portfolio_name']=PRIVATE_PORTFOLIO
    bets['portfolio_name']=PRIVATE_PORTFOLIO
    write_exports(private,bets,output_all=STATE/'forecasts.csv',output_bets=STATE/'bets.csv')
    append_tracking_rows(build_tracking_rows(bets,portfolio_name=PRIVATE_PORTFOLIO),LEDGER)
    manifest=ROOT/'inference/releases/draw_pooled_2026_09_05/manifest.json'
    receipt={'portfolio':PRIVATE_PORTFOLIO,'registered_at':ACTIVATED_AT,
        'collected_at':datetime.now(timezone.utc).isoformat(),'scored_rows':len(private),
        'source_release_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'source_forecast_sha256':hashlib.sha256((STATE/'forecasts.csv').read_bytes()).hexdigest(),
        'forecast_receipts':[{'fixture_id':str(r.get('fixture_id','')),'kickoff_utc':str(r.get('kickoff_utc','')),
            'strategy':str(r['strategy_name']),'signal':float(r['predicted_probability']),
            'odds':float(r['selected_odds']),'selected':bool(r['recommended_bet'])}
            for r in private.to_dict(orient='records')]}
    (STATE/'last_collection.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')


def export_report():
    import pandas as pd
    from inference.portfolio_presets import PRODUCTION_POOLED_STRATEGIES
    from inference.live_tracking import canonicalize_tracking_rows
    ledger=canonicalize_tracking_rows(pd.read_csv(LEDGER))
    ledger=ledger[ledger.portfolio_name.eq(PRIVATE_PORTFOLIO)].copy()
    if len(ledger) and not ledger.league.isin(PRIVATE_LEAGUES).all():raise ValueError('Wrong private observation domain')
    if len(ledger) and not (pd.to_datetime(ledger.prediction_generated_at_utc,utc=True)>=pd.Timestamp(ACTIVATED_AT)).all():
        raise ValueError('No retrospective enrollment is allowed')
    def stats(rows):
        settled=rows[rows.result_status.isin(['won','lost'])]
        profit=sum(float(r.selected_odds)-1 if r.result_status=='won' else -1 for r in settled.itertuples())
        return {'settled':len(settled),'pending':int((~rows.result_status.isin(['won','lost','void'])).sum()),
            'wins':int(settled.result_status.eq('won').sum()),'profit':round(profit,8),
            'roi':profit/len(settled) if len(settled) else None}
    strategies=[]
    for s in PRODUCTION_POOLED_STRATEGIES:
        if s.bet_league not in PRIVATE_LEAGUES:continue
        rows=ledger[ledger.strategy_names.fillna('').eq(s.name)]
        strategies.append({'id':s.name,'label':'Serie A · Nul' if s.bet_league=='Serie_A' else 'Premier League · Nul',
            'code':'I01' if s.bet_league=='Serie_A' else 'E01','metrics':stats(rows)})
    tickets=[]
    for r in ledger.to_dict(orient='records'):
        status=r['result_status'];profit=None if status not in ['won','lost','void'] else 0 if status=='void' else float(r['selected_odds'])-1 if status=='won' else -1
        kickoff=r.get('kickoff_utc')
        tickets.append({'id':r['snapshot_key'],'date':kickoff if isinstance(kickoff,str) and kickoff.strip() else r['date'],
            'home':r['team_name'],'away':r['opponent_name'],'league':r['league'],
            'strategy':r['strategy_names'],'odds':float(r['selected_odds']),'status':status,'profit':profit})
    collection=json.loads((STATE/'last_collection.json').read_text(encoding='utf8')) if (STATE/'last_collection.json').exists() else None
    result={'schemaVersion':1,'private':True,'portfolio':PRIVATE_PORTFOLIO,'registeredAt':ACTIVATED_AT,
        'updatedAt':datetime.now(timezone.utc).isoformat(),'status':'ready' if collection or len(ledger) else 'unavailable',
        'strategies':strategies,'tickets':tickets,'collection':collection,
        'note':'Suivi virtuel depuis le passage en observation ; les anciens paris publics restent dans leur journal original.'}
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['pull','evaluate-push','settle'])
    args=parser.parse_args()
    from inference.supabase_prediction_store import pull,push
    STATE.mkdir(parents=True,exist_ok=True)
    if args.action=='pull':
        pull(LEDGER,STATUS,portfolio_name=PRIVATE_PORTFOLIO)
        return
    if args.action=='evaluate-push':
        subprocess.run([sys.executable,'-m','inference.evaluate_live_portfolio','--ledger',str(LEDGER),
            '--portfolio',PRIVATE_PORTFOLIO,'--freeze-date',PRIVATE_FREEZE_DATE,'--output',str(STATE/'evaluation.csv'),
            '--summary-output',str(STATE/'summary.json'),'--update-ledger'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    else:
        import pandas as pd
        from inference.result_monitor import collect_results_for_due_rows,settle_due_predictions
        from inference.live_tracking import refresh_pending_fixture_dates_from_catalog
        rows=pd.read_csv(LEDGER)
        now=pd.Timestamp.now(tz='Europe/Paris').tz_localize(None)
        results,_=collect_results_for_due_rows(rows,now=now,minimum_elapsed_minutes=105,
            portfolio_name=PRIVATE_PORTFOLIO,timeout_seconds=30)
        rows,_=refresh_pending_fixture_dates_from_catalog(rows,results)
        rows,_=settle_due_predictions(rows,results,now=now,minimum_elapsed_minutes=105,portfolio_name=PRIVATE_PORTFOLIO)
        rows.to_csv(LEDGER,index=False)
    push(LEDGER,STATUS,portfolio_name=PRIVATE_PORTFOLIO)
    export_report()
    print('Private observation stored; public ledger unchanged.')


if __name__=='__main__':main()
