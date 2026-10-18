"""Versioned publication scope; the September model release stays immutable.

The model portfolio identity and its already published ledger are preserved.
This new publication version restricts future public recommendations, not model
weights or the recorded outcomes of earlier decisions.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from inference.english_away_public import STRATEGY as ENGLISH_STRATEGY, ACTIVATED_AT as ENGLISH_ACTIVATED_AT, qualifies

VERSION = 'bundesliga_draw_epl_away_strict_2026_10_18'
ACTIVATED_AT = '2026-10-18T12:09:15+00:00'
PRIVATE_PORTFOLIO = 'observation_italy_epl_2026_10_18'
PRIVATE_FREEZE_DATE = '2026-10-18'
PUBLIC_LEAGUES = frozenset({'Bundesliga','EPL'})
PRIVATE_LEAGUES = frozenset({'Serie_A','EPL'})
# This decision was public before the restriction. It must remain auditable,
# continue to settle and never be advertised as a new current recommendation.
LEGACY_HISTORY = frozenset({('Serie_A','2026-10-18','AC Milan','Atalanta')})


def public_row(row):
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


def original_history(row):
    return (row.get('league'),str(row.get('date',''))[:10],row.get('homeTeam'),row.get('awayTeam')) in LEGACY_HISTORY


def apply_publication_policy(payload):
    """Idempotent publication boundary, preserving the original public history."""
    data=copy.deepcopy(payload)
    meta=data.setdefault('meta',{})
    meta.update(publicationVersion=VERSION,publicationActivatedAt=ENGLISH_ACTIVATED_AT,
        publicLeagues=sorted(PUBLIC_LEAGUES),publicOutcomes=['draw','away_win'],stakeUnits=1,
        publicStrategies=[{'league':'Bundesliga','outcome':'draw','label':'Bundesliga · match nul'},
                          {'id':ENGLISH_STRATEGY,'league':'EPL','outcome':'away_win','label':'Premier League · victoire extérieure',
                           'oddsMin':2,'oddsMax':6,'evThreshold':.10,'priceHaircut':.02,
                           'activatedAt':ENGLISH_ACTIVATED_AT,'trainingMaxSeason':2024}],
        historyScope='published_history_including_prior_publication_versions')
    predictions=[p for p in data.get('predictions',[]) if public_row(p)]
    for p in predictions:
        p['stakeUnits']=1
    data['predictions']=predictions
    activity=[]
    for source in data.get('activity',[]):
        row=copy.deepcopy(source)
        if not public_row(row):
            if not original_history(row):
                continue
            row['historicalOnly']=True
            row['publicationLabel']='Ancien pari publié · suivi uniquement'
        activity.append(row)
    data['activity']=activity
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
    tracking=data.setdefault('tracking',{})
    tracking['pending']=pending
    tracking['pendingAll']=sum(not r.get('historicalOnly') and r.get('status') not in {'won','lost','void'} for r in activity)
    tracking['historyLabel']='Tous les paris déjà publiés, anciennes versions comprises'
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
            or any(not public_row(r) and (not original_history(r) or not r.get('historicalOnly')) for r in original.get('activity',[]))):
            raise SystemExit('Publication scope or preserved history is invalid.')
    else:
        temp=args.snapshot.with_suffix('.json.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        temp.replace(args.snapshot)
    print('Public scope:',VERSION,'recommendations:',len(data['predictions']))


if __name__=='__main__':main()
