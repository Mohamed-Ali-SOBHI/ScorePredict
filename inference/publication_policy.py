"""Versioned publication scope; the September model release stays immutable.

The model portfolio identity and its already published ledger are preserved.
The publication boundary restricts recommendations and displayed history, not
model weights or the durable records of earlier decisions.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime,timezone,timedelta
import json
import math
from pathlib import Path
from inference.english_away_public import STRATEGY as ENGLISH_STRATEGY, ACTIVATED_AT as ENGLISH_ACTIVATED_AT, qualifies
from inference.bundesliga_draw_public import (VERSION as DRAW_FILTER_VERSION,
    ACTIVATED_AT as DRAW_FILTER_ACTIVATED_AT, EV_THRESHOLD, PRICE_HAIRCUT, EDGE_MIN)

VERSION = 'bundesliga_original_restored_epl_away_preserved_history_2026_10_25'
ACTIVATED_AT = '2026-10-18T12:09:15+00:00'
PRIVATE_PORTFOLIO = 'observation_italy_epl_2026_10_18'
PRIVATE_FREEZE_DATE = '2026-10-18'
PUBLIC_LEAGUES = frozenset({'Bundesliga','EPL'})
PRIVATE_LEAGUES = frozenset({'Serie_A','EPL'})


def public_row(row):
    # Never expose private observations, even if accidentally passed to a renderer.
    strategy = row.get('strategy', row.get('strategy_names', row.get('strategy_name', '')))
    if str(strategy).startswith('private_bundesliga_recalibrated_') or str(row.get('portfolio_name','')).startswith('private_bundesliga_recalibrated_'):
        return False
    outcome=row.get('outcome',row.get('selected_outcome'))
    if outcome is None:
        outcome='draw' if row.get('outcomeLabel') in {'Match nul','Nul'} else ''
    if row.get('league') == 'Bundesliga':
        return outcome == 'draw'
    if row.get('league') != 'EPL' or outcome not in {'away','away_win'}:
        return False
    strategy = row.get('strategy', row.get('strategy_names', row.get('strategy_name', '')))
    if strategy != ENGLISH_STRATEGY:
        return False
    try:
        recorded = datetime.fromisoformat(row.get('recordedAt', row.get('prediction_generated_at_utc', '')).replace('Z','+00:00'))
        if recorded < datetime.fromisoformat(ENGLISH_ACTIVATED_AT):
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    return qualifies(row.get('modelProbability',row.get('predicted_probability')),row.get('odds',row.get('selected_odds')))


def public_totals(activity):
    """Live totals use the very same visible tickets as the public journal."""
    settled=[row for row in activity if row.get('status') in {'won','lost'}]
    won=sum(row.get('status')=='won' for row in settled)
    profits=[]
    for row in settled:
        try:
            value=float(row['profitUnits'])
            profits.append(value if math.isfinite(value) else None)
        except (KeyError,ValueError,TypeError):
            profits.append(None)
    profit=round(sum(profits),8) if all(value is not None for value in profits) else None
    return {'settled':len(settled),'won':won,'lost':len(settled)-won,
            'void':sum(row.get('status')=='void' for row in activity),
            'profit':profit,'roi':profit/len(settled) if settled and profit is not None else None}


def apply_publication_policy(payload):
    """Public display scope only; the durable ledger and private archives remain intact."""
    data=copy.deepcopy(payload)
    meta=data.setdefault('meta',{})
    meta.update(publicationVersion=VERSION,publicationActivatedAt=ENGLISH_ACTIVATED_AT,
        publicLeagues=sorted(PUBLIC_LEAGUES),publicOutcomes=['draw','away_win'],stakeUnits=1,
        publicStrategies=[{'league':'Bundesliga','outcome':'draw','label':'Bundesliga · match nul',
                           'filterVersion':DRAW_FILTER_VERSION,'filterActivatedAt':DRAW_FILTER_ACTIVATED_AT,
                           'oddsMin':2.2,'oddsMaxExclusive':10,'evThreshold':EV_THRESHOLD,
                           'priceHaircut':PRICE_HAIRCUT,'edgeMin':EDGE_MIN,'marketFavoriteMode':'nonfavorite',
                           'historyIncludesPreviousFilters':True},
                          {'id':ENGLISH_STRATEGY,'league':'EPL','outcome':'away_win','label':'Premier League · victoire extérieure',
                           'oddsMin':2,'oddsMax':6,'evThreshold':.10,'priceHaircut':.02,
                           'activatedAt':ENGLISH_ACTIVATED_AT,'trainingMaxSeason':2024}],
        historyScope='published_tickets_of_current_public_strategies',
        historyPolicyActivatedAt='2026-10-19T06:57:43+00:00')
    predictions=[p for p in data.get('predictions',[]) if public_row(p)]
    for p in predictions:
        p['stakeUnits']=1
    data['predictions']=predictions
    activity=[row for row in data.get('activity',[]) if public_row(row) and not row.get('historicalOnly')]
    data['activity']=activity
    totals=public_totals(activity)
    summary=data.setdefault('summary',{})
    summary['upcomingBets']=len(predictions)
    summary['currentRecommendations']=sum(p.get('isCurrentRecommendation') is True for p in predictions)
    now=datetime.now(timezone.utc)
    def future(row):
        try:
            stamp=datetime.fromisoformat(row['date'].replace('Z','+00:00'))
            return stamp.tzinfo is not None and now<=stamp<now+timedelta(days=1)
        except (KeyError,ValueError,TypeError):
            return False
    pending=sum(not r.get('historicalOnly') and r.get('status') not in {'won','lost','void'} and future(r) for r in activity)
    summary['pendingPredictions']=pending
    summary.update(settledLiveBets=totals['settled'],wonPredictions=totals['won'],lostPredictions=totals['lost'],
                   liveProfitUnits=totals['profit'],liveReturn=totals['roi'],liveRoi=totals['roi'])
    tracking=data.setdefault('tracking',{})
    tracking['pending']=pending
    tracking['pendingAll']=sum(not r.get('historicalOnly') and r.get('status') not in {'won','lost','void'} for r in activity)
    tracking.update(verified=totals['settled'],won=totals['won'],lost=totals['lost'],void=totals['void'],
                    wonBetsCount=totals['won'],hitRate=totals['won']/totals['settled'] if totals['settled'] else None,
                    historyLabel='Paris publiés des stratégies actuellement affichées')
    data.setdefault('performance',{}).setdefault('live',{}).update(
        settledBets=totals['settled'],wonBets=totals['won'],profitUnits=totals['profit'],roi=totals['roi'])
    scope=data.get('performance',{}).get('scope')
    if scope and scope.get('strategyCount')==4:
        scope['label']='Simulation historique du portefeuille précédent · quatre stratégies'
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=Path('production/static/data/dashboard.json'))
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    original=json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    data=apply_publication_policy(original)
    if args.check:
        if (original.get('meta',{}).get('publicationVersion')!=VERSION
            or not all(public_row(p) for p in original.get('predictions',[]))
            or original.get('summary',{}).get('upcomingBets')!=len(original.get('predictions',[]))
            or any(not public_row(r) or r.get('historicalOnly') for r in original.get('activity',[]))
            or any(original.get('summary',{}).get(key)!=data['summary'][key] for key in
                   ['settledLiveBets','wonPredictions','lostPredictions','liveProfitUnits','liveReturn'])):
            raise SystemExit('Public strategy scope or displayed totals are invalid.')
    else:
        temp=args.snapshot.with_suffix('.json.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        temp.replace(args.snapshot)
    print('Public scope:',VERSION,'recommendations:',len(data['predictions']))


if __name__=='__main__':main()
