"""Export a local read-only view of the sealed nine-strategy experiment."""
from __future__ import annotations
import argparse,hashlib,importlib,json,os,subprocess,sys,tarfile,tempfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/'production/observation_history.json'
OUTPUT=ROOT.parent/'suivi_prive_9/data.json'

def require_private_output(path):
    if Path(path).resolve().is_relative_to((ROOT/'production/static').resolve()):
        raise ValueError('Le suivi personnel ne doit pas être écrit dans le site public.')

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def atomic_write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(temp,path)

def adapter():
    sys.path.insert(0,str(ROOT/'paper_compare9'))
    return importlib.import_module('compare9')

def metrics(tickets):
    settled=[t for t in tickets if t['profit'] is not None]
    pending=[t for t in tickets if t['profit'] is None]
    stake=sum(t['stake'] for t in settled);profit=sum(t['profit'] for t in settled)
    return {'settled':len(settled),'wins':sum(t['status']=='won' for t in settled),'profit':round(profit,8),
        'roi':profit/stake if stake else None,'pending':len(pending),'stake':stake}

def metadata():
    reg=read(ROOT/'paper_compare9/registration.json');members=read(ROOT/'paper_positive15/members.json')
    leagues={'EPL':'Premier League','Bundesliga':'Bundesliga','Ligue_1':'Ligue 1','Serie_A':'Serie A'}
    outcomes={'home':'Domicile','away':'Extérieur','draw':'Nul'}
    models={'local_price_only':'Modèle local basé sur les cotes','local_sport_only':'Modèle sportif local',
            'residual_sport_recency':'Modèle résiduel sportif, saisons récentes','residual_price':'Modèle résiduel basé sur les cotes'}
    strategies=[]
    for m in members:
        if m['id'] not in reg['nine_members']:continue
        strategies.append({'id':m['id'],'code':f'S{len(strategies)+1:02}',
            'label':leagues[m['league']]+' · '+outcomes[m['outcome']],
            'league':m['league'],'model':models[m['model']],'threshold':m['threshold'],
            'filter':'Équipes proches et faible total de buts attendus' if m['profile']=='low_goal_parity' else None})
    assert [s['id'] for s in strategies]==reg['nine_members']
    return strategies

def base_payload():
    history=read(HISTORY);strategies=metadata()
    if history['nineMembers']!=[s['id'] for s in strategies]:raise ValueError('Historical strategy selection differs')
    return {'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'status':'unavailable',
        'stakeUnits':1,'strategies':strategies,'history':history,'live':None,'tickets':[]}

def build(source_dir,comparison_dir):
    compare=adapter();previous_source=compare.source_state.STATE;previous_state=compare.STATE
    compare.source_state.STATE=Path(source_dir);compare.STATE=Path(comparison_dir)
    try:
        reg=compare.check_registration()
        source_checkpoint,source_events=compare.source_state.verify()
        checkpoint,events=compare.verify()
        prefix=source_events[:checkpoint['source_event_count']]
        if len(prefix)!=checkpoint['source_event_count'] or compare.digest(prefix)!=checkpoint['source_events_sha256']:
            raise ValueError('Source history no longer matches enrolled comparison')
        if read(Path(comparison_dir)/'registration.json')!=reg:raise ValueError('Saved registration differs')
        source_forecasts={e['identity']:e['payload'] for e in source_events if e['kind']=='forecast'}
        source_results={e['identity']:e['payload'] for e in source_events if e['kind']=='settlement'}
        payloads=[e['payload'] for e in events]
        forecasts={p['fixture_id']:p for p in payloads if p.get('type')=='forecast'}
        settlements={p['fixture_id']:p for p in payloads if p.get('type')=='settlement'}
        for identity,f in forecasts.items():
            compare.validate_forecast(f,reg,compare.stamp(f['recorded_at_utc']))
            if compare.digest(source_forecasts.get(identity))!=f['source_forecast_sha256']:raise ValueError('Enrolled source replaced')
        for identity,s in settlements.items():
            f=forecasts.get(identity)
            if f is None or s['forecast_sha256']!=compare.digest(f) or s['source_settlement']!=source_results.get(identity):
                raise ValueError('Settlement does not match enrolled source')
        rows,tickets,_=compare.metrics(forecasts,settlements)
        saved=read(Path(comparison_dir)/'report.json')
        if saved['portfolios']!=rows or saved['forecasts']!=len(forecasts):raise ValueError('Published metrics differ from journal')
        result=base_payload();nine=set(reg['nine_members'])
        result['tickets']=[t for t in tickets if t['portfolio']=='bundesliga_plus9']
        if len(result['tickets'])!=len({t['fixture_id'] for t in result['tickets']}):raise ValueError('Duplicate union ticket')
        individual={key:[] for key in reg['nine_members']}
        for identity,f in forecasts.items():
            source=f['source_forecast'];settlement=settlements.get(identity)
            for choice in source['decisions']:
                if choice['member'] not in nine or not choice['selected']:continue
                won=None if settlement is None else choice['outcome']==settlement['source_settlement']['outcome']
                individual[choice['member']].append({'stake':1,'profit':None if won is None else choice['odds']*won-1,
                    'status':'pending' if won is None else 'won' if won else 'lost'})
        state=saved['status']['state']
        source_state=read(Path(source_dir)/'report.json')['status']['state']
        result.update(status='ready' if state=='collected' and source_state=='collected' else 'attention',live={
            'registeredAt':reg['registered_at_utc'],'updatedAt':saved['status']['finished_at_utc'],
            'sourceUpdatedAt':saved['status'].get('source15_finished_at_utc'),'state':state,'fixtures':len(forecasts),
            'baseline':metrics([t for t in tickets if t['portfolio']=='reference']),
            'union':metrics(result['tickets']),'individual':{key:metrics(value) for key,value in individual.items()},
            'evidenceHash':checkpoint['events_sha256'],'sourceEvidenceHash':source_checkpoint['events_sha256']})
        return result
    finally:compare.source_state.STATE=previous_source;compare.STATE=previous_state

def fetch_state(branch,destination):
    ref='refs/remotes/origin/'+branch
    subprocess.run(['git','fetch','--quiet','--no-tags','origin',branch+':'+ref],cwd=ROOT,check=True,timeout=120)
    # Extract a Git-created archive with traversal protection, never executing state files.
    archive=subprocess.check_output(['git','archive','--format=tar',ref],cwd=ROOT,timeout=60)
    import io
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(destination,filter='data')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-state',type=Path);parser.add_argument('--comparison-state',type=Path)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    require_private_output(args.output)
    try:
        if args.source_state and args.comparison_state:result=build(args.source_state,args.comparison_state)
        else:
            with tempfile.TemporaryDirectory(prefix='scorepredict-observation-') as temp:
                temp=Path(temp);source=temp/'source';comparison=temp/'comparison'
                fetch_state('observation-positive15-state',source)
                fetch_state('observation-compare9-state',comparison)
                result=build(source,comparison)
    except Exception as error:
        result=base_payload();result['message']='Le dernier suivi ne peut pas être vérifié.'
        print('::warning::Observation export unavailable: '+str(error),file=sys.stderr)
    atomic_write(args.output,result)
    print('Observation snapshot:',result['status'],len(result['tickets']),'unique tickets')

if __name__=='__main__':main()
