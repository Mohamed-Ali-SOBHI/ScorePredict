"""Prospective paired comparison, derived from immutable positive15 forecasts."""
from pathlib import Path
from datetime import timedelta
import csv,hashlib,html,json,os,sys,traceback

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'paper_positive15'
sys.path.insert(0,str(SOURCE))
import paper_core as pc
import cloud_state as source_state
utcnow=pc.utcnow
stamp=pc.stamp
digest=pc.digest
STATE=Path(os.environ.get('COMPARE9_STATE_DIR',str(ROOT/'state'))).resolve()
PORTFOLIOS=[('reference','Nuls Bundesliga seuls'),('bundesliga_plus9','Nuls Bundesliga + 9 stratégies'),
            ('bundesliga_plus15','Nuls Bundesliga + 15 stratégies, même période')]


def read(path):return json.loads(path.read_text(encoding='utf8'))
def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(tmp,path)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def check_registration():
    reg=read(ROOT/'registration.json')
    for name,value in reg['frozen_sha256'].items():
        if sha(ROOT/name)!=value:raise ValueError('Frozen comparison changed: '+name)
    source=source_state.check_registration()
    if digest(source)!=reg['source_registration_sha256']:raise ValueError('Source15 protocol changed')
    ordered=[m['id'] for m in pc.MEMBERS[1:] if m['id'] in reg['nine_members']]
    if len(ordered)!=9 or ordered!=reg['nine_members']:raise ValueError('Nine members or priority changed')
    return reg


def project(source,nine):
    reference=source['reference']
    original=source['portfolios']['bundesliga_plus15']
    if reference is not None:
        anchor={'source':'reference','outcome':reference['outcome'],'odds':reference['odds'],'stake':1.}
        nine_bet=anchor.copy()
    else:
        anchor=None;choices={c['member']:c for c in source['decisions']}
        chosen=next((choices[m] for m in nine if m in choices and choices[m]['selected']),None)
        nine_bet=None if chosen is None else {'source':chosen['member'],'outcome':chosen['outcome'],'odds':chosen['odds'],'stake':1.}
    return {'reference':anchor,'bundesliga_plus9':nine_bet,'bundesliga_plus15':original}


def validate_forecast(receipt,reg,now):
    f=receipt['source_forecast'];created=stamp(receipt['recorded_at_utc']);kickoff=stamp(f['kickoff_utc'])
    if receipt['type']!='forecast' or receipt['fixture_id']!=f['fixture_id']:raise ValueError('Wrong forecast identity')
    if receipt['registration_sha256']!=digest(reg):raise ValueError('Wrong comparison protocol')
    if not stamp(reg['registered_at_utc'])<=created<=now:raise ValueError('Invalid enrollment time')
    if not timedelta(minutes=5)<=kickoff-now<=timedelta(hours=24):raise ValueError('No past or started match may enter comparison')
    if stamp(f['recorded_at_utc'])>created:raise ValueError('Source forecast unavailable at enrollment')
    if f['registration_sha256']!=reg['source_registration_sha256']:raise ValueError('Wrong source protocol')
    if receipt['source_forecast_sha256']!=digest(f):raise ValueError('Source forecast altered')
    source_reg=read(SOURCE/'registration.json')
    pc.validate_receipt(f,source_reg['registered_at_utc'],stamp(f['recorded_at_utc']))
    if receipt['portfolios']!=project(f,reg['nine_members']):raise ValueError('Portfolio or price altered')


class Journal:
    # Reuse the sealed source's append-only hash-chain storage. Typed comparison
    # events use generic run envelopes; their forecast/settlement checks are here.
    def __init__(self,path,reg):self.reg=reg;self.store=pc.Journal(path,reg)
    def records(self,kind):return {p['fixture_id']:p for p in self.store.records('run').values() if p['type']==kind}
    def forecast(self,payload):
        validate_forecast(payload,self.reg,utcnow())
        return self.store.append('run','forecast:'+payload['fixture_id'],payload)
    def settlement(self,payload):
        forecasts=self.records('forecast');f=forecasts.get(payload['fixture_id'])
        if f is None:raise ValueError('Settlement without enrolled forecast')
        s=payload['source_settlement'];seen=stamp(s['result_seen_at_utc']);kickoff=stamp(f['source_forecast']['kickoff_utc'])
        if payload['forecast_sha256']!=digest(f) or s['forecast_sha256']!=f['source_forecast_sha256']:raise ValueError('Wrong settlement forecast')
        if not kickoff+timedelta(hours=2)<=seen<=utcnow():raise ValueError('Result not available')
        h,a=s['home_goals'],s['away_goals']
        if type(h) is not int or type(a) is not int or min(h,a)<0:raise ValueError('Invalid result goals')
        expected='home' if h>a else 'away' if h<a else 'draw'
        if s['outcome']!=expected:raise ValueError('Result outcome differs from goals')
        return self.store.append('run','settlement:'+payload['fixture_id'],payload)
    def run(self,status):return self.store.append('run','collection:'+status['run_id'],{'type':'collection',**status})
    def export(self):return self.store.export()
    def close(self):self.store.db.close()


def inventory():
    return {p.relative_to(STATE).as_posix():sha(p) for p in sorted(STATE.rglob('*')) if p.is_file()
        and '.git' not in p.relative_to(STATE).parts and p.name not in ['checkpoint.json','collector.lock']}
def verify():
    reg=check_registration();checkpoint=read(STATE/'checkpoint.json')
    if checkpoint['registration_sha256']!=digest(reg) or checkpoint['files']!=inventory():raise ValueError('Comparison state missing or altered')
    if not (STATE/'journal.sqlite3').is_file():raise ValueError('Comparison journal missing; no automatic reset')
    journal=Journal(STATE/'journal.sqlite3',reg)
    try:
        events=journal.export()
        if checkpoint['events_sha256']!=digest(events):raise ValueError('Comparison checkpoint changed')
    finally:journal.close()
    return checkpoint,events


def metrics(forecasts,settlements):
    rows=[];tickets=[];nine_ids=set(read(ROOT/'registration.json')['nine_members'])|{'Bundesliga_anchor'}
    for portfolio,label in PORTFOLIOS:
        completed=[];pending=[];daily={}
        for identity,f in forecasts.items():
            bet=f['portfolios'][portfolio]
            if bet is None:continue
            source=f['source_forecast'];s=settlements.get(identity);won=None if s is None else bet['outcome']==s['source_settlement']['outcome']
            profit=None if s is None else bet['stake']*(bet['odds']*won-1)
            ticket={'portfolio':portfolio,'fixture_id':identity,'league':source['league'],'home_team':source['home_team'],'away_team':source['away_team'],
                'kickoff_utc':source['kickoff_utc'],'enrolled_at_utc':f['recorded_at_utc'],'source_recorded_at_utc':source['recorded_at_utc'],
                **bet,'status':'pending' if s is None else 'won' if won else 'lost','profit':profit,
                'selected_members':[c['member'] for c in source['decisions'] if c['selected']
                    and (portfolio=='bundesliga_plus15' or portfolio=='bundesliga_plus9' and c['member'] in nine_ids
                         or portfolio=='reference' and c['member']=='Bundesliga_anchor')]}
            tickets.append(ticket)
            if s is None:pending.append(ticket)
            else:
                completed.append(ticket);day=source['kickoff_utc'][:10];daily[day]=daily.get(day,0)+profit
        high=equity=drawdown=0
        for day,gain in sorted(daily.items()):equity+=gain;high=max(high,equity);drawdown=max(drawdown,high-equity)
        stake=sum(t['stake'] for t in completed)
        rows.append({'portfolio':portfolio,'label':label,'committed_bets':len(completed)+len(pending),'settled_bets':len(completed),
            'pending_bets':len(pending),'pending_stake':sum(t['stake'] for t in pending),'settled_stake':stake,
            'wins':sum(t['status']=='won' for t in completed),'profit':equity,'roi':equity/stake if stake else None,
            'max_daily_drawdown':drawdown,'additional_profit':sum(t['profit'] for t in completed if t['source']!='reference')})
    nine,fifteen=rows[1:];diff={'profit_9_minus_15':nine['profit']-fifteen['profit'],
        'settled_stake_9_minus_15':nine['settled_stake']-fifteen['settled_stake'],
        'roi_9_minus_15':None if nine['roi'] is None or fifteen['roi'] is None else nine['roi']-fifteen['roi'],
        'same_outcome':0,'different_outcome':0,'nine_only':0,'fifteen_only':0}
    for f in forecasts.values():
        a,b=(f['portfolios'][p] for p in ['bundesliga_plus9','bundesliga_plus15'])
        if a and b:diff['same_outcome' if a['outcome']==b['outcome'] else 'different_outcome']+=1
        elif a:diff['nine_only']+=1
        elif b:diff['fifteen_only']+=1
    return rows,tickets,diff


def make_report(journal,status,source_lifetime=None):
    forecasts=journal.records('forecast');settlements=journal.records('settlement');rows,tickets,diff=metrics(forecasts,settlements)
    report={'registered_at_utc':journal.reg['registered_at_utc'],'status':status,'forecasts':len(forecasts),'settled_fixtures':len(settlements),
        'portfolios':rows,'comparison':diff,'fifteen_lifetime_separate':source_lifetime,'production_changed':False,'historical_bets_imported':False}
    write(STATE/'report.json',report);write(STATE/'tickets.json',tickets)
    write(STATE/'evidence.json',{'registration_sha256':digest(journal.reg),'events':journal.export()})
    for name,values in [('comparison.csv',rows),('tickets.csv',tickets)]:
        fields=list(rows[0]) if name=='comparison.csv' else ['portfolio','fixture_id','league','home_team','away_team','kickoff_utc','enrolled_at_utc','source_recorded_at_utc','source','outcome','odds','stake','status','profit','selected_members']
        with (STATE/name).open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
            for value in values:
                if 'selected_members' in value:value=value|{'selected_members':' ; '.join(value['selected_members'])}
                writer.writerow(value)
    lines=['# Comparaison prospective : 9 stratégies contre 15, avec les nuls Bundesliga','',
        '**Simulation à 1 unité par pari. Aucun pari déjà réglé n’est importé.**','',
        'Inscription de la comparaison : '+journal.reg['registered_at_utc'],
        'Dernier passage : '+status['finished_at_utc']+' — '+status['state'],
        f"Matchs inscrits avant le coup d’envoi : {len(forecasts)}. Résultats confirmés : {len(settlements)}.",'',
        '| Portefeuille | Réglés | En attente | Mises réglées | Gain net (u) | Rendement | Baisse max (u) |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        roi='—' if r['roi'] is None else f"{100*r['roi']:.2f} %"
        lines.append(f"| {r['label']} | {r['settled_bets']} | {r['pending_bets']} | {r['settled_stake']:.2f} | {r['profit']:.2f} | {roi} | {r['max_daily_drawdown']:.2f} |")
    lines+=['',f"Différence de gain des 9 moins les 15 : {diff['profit_9_minus_15']:.2f} u.",'',
        'Les trois lignes utilisent les mêmes matchs inscrits, prévisions figées et cotes. Chaque portefeuille conserve au maximum une issue et une unité par match : Bundesliga est prioritaire, puis l’ordre initial des stratégies retenues. Un pari commun aux deux portefeuilles est une comparaison, pas une double mise réelle. Les lignes ne doivent pas être additionnées.','',
        'Un match déjà prévu dans le suivi des 15 peut entrer dans la comparaison uniquement si son coup d’envoi est encore à plus de cinq minutes et moins de vingt-quatre heures lors de son inscription. Le prix reste celui de la prévision source ; aucun nouveau prix n’est inventé. Les matchs démarrés ou déjà réglés sont exclus.','',
        'Les 9 sont les stratégies positives sur les tests annuels 2025/26 et le replay 2026/27 arrêté au 17 octobre, avec les filtres actuels. Ce choix est rétrospectif : seuls les résultats après inscription évaluent prospectivement ce sous-ensemble. Aucun filtre ni modèle n’est réentraîné.','',
        'Le suivi complet des 15 conserve son propre historique ; sa ligne de comparaison ci-dessus ne porte que sur le périmètre commun depuis cette inscription. Le gain et le rendement excluent les paris encore en attente.','',
        '[Paris et cotes](tickets.json) · [Comparaison CSV](comparison.csv) · [Protocole figé](registration.json) · [Preuves](evidence.json) · [Suivi complet des 15](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/tree/observation-positive15-state)','',
        'Collecte après chaque passage réussi du workflow des 15, quatre fois par jour et après les prévisions de production. Les horaires GitHub peuvent subir un retard.']
    (STATE/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    trs=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['label'],r['settled_bets'],r['pending_bets'],f"{r['profit']:.2f}",'—' if r['roi'] is None else f"{100*r['roi']:.2f} %"])+'</tr>' for r in rows)
    (STATE/'rapport.html').write_text('<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Comparaison des 9 et des 15</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px}table{border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #ccc}</style><h1>9 stratégies contre 15, avec les nuls Bundesliga</h1><p>Simulation prospective à 1 unité par match. Même cohorte et mêmes cotes ; une seule issue par match dans chaque portefeuille.</p><p>Début : '+html.escape(journal.reg['registered_at_utc'])+'. Dernier passage : '+html.escape(status['finished_at_utc'])+'.</p><table><tr><th>Portefeuille</th><th>Réglés</th><th>En attente</th><th>Gain (u)</th><th>Rendement</th></tr>'+trs+'</table><p><a href="README.md">Règles et interprétation</a> · <a href="tickets.json">Paris et cotes</a> · <a href="report.json">Comparaison complète</a></p></html>',encoding='utf8')
    return report


def seal(journal,status,prior,source_checkpoint=None,source_lifetime=None):
    events=journal.export()
    if events[:len(prior)]!=prior:raise ValueError('Earlier comparison evidence changed')
    make_report(journal,status,source_lifetime)
    checkpoint={'registration_sha256':digest(journal.reg),'events_sha256':digest(events),'event_count':len(events),
        'source_event_count':0 if source_checkpoint is None else source_checkpoint['event_count'],
        'source_events_sha256':digest([]) if source_checkpoint is None else source_checkpoint['events_sha256'],
        'sealed_at_utc':utcnow().isoformat(),'github_run_id':os.environ.get('GITHUB_RUN_ID'),'files':inventory()}
    write(STATE/'checkpoint.json',checkpoint)


def initialize():
    reg=check_registration()
    if STATE.exists():raise ValueError('Never overwrite a comparison state')
    STATE.mkdir(parents=True);(STATE/'.gitattributes').write_text('* -text\n',encoding='utf8')
    write(STATE/'registration.json',reg);journal=Journal(STATE/'journal.sqlite3',reg)
    try:seal(journal,{'state':'registered_waiting_first_capture','finished_at_utc':utcnow().isoformat()},[])
    finally:journal.close()
    verify()


def collect():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise ValueError('Live comparison runs on GitHub Actions only')
    checkpoint,prior=verify();reg=check_registration()
    lock=STATE/'collector.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    journal=Journal(STATE/'journal.sqlite3',reg);source_checkpoint=None;lifetime=None
    run_id=utcnow().strftime('%Y%m%dT%H%M%S%fZ')
    try:
        source_checkpoint,events=source_state.verify()
        prefix=events[:checkpoint['source_event_count']]
        if len(prefix)!=checkpoint['source_event_count'] or digest(prefix)!=checkpoint['source_events_sha256']:raise ValueError('Source15 history changed or disappeared')
        source_report=read(source_state.STATE/'report.json')
        lifetime=next(r for r in source_report['portfolios'] if r['portfolio']=='bundesliga_plus15')
        if source_report['status']['state']!='collected':raise ValueError('Source15 collection incomplete')
        if utcnow()-stamp(source_report['status']['finished_at_utc'])>timedelta(hours=24):raise ValueError('Source15 report stale')
        source_forecasts={e['identity']:e['payload'] for e in events if e['kind']=='forecast'}
        source_settlements={e['identity']:e['payload'] for e in events if e['kind']=='settlement'}
        enrolled=journal.records('forecast');new=settled=0
        for identity,f in source_forecasts.items():
            if identity in enrolled or identity in source_settlements:continue
            now=utcnow()
            if not timedelta(minutes=5)<=stamp(f['kickoff_utc'])-now<=timedelta(hours=24):continue
            receipt={'type':'forecast','fixture_id':identity,'registration_sha256':digest(reg),'recorded_at_utc':now.isoformat(),
                'source_forecast_sha256':digest(f),'source_forecast':f,'source_checkpoint_sha256':digest(source_checkpoint),
                'portfolios':project(f,reg['nine_members'])}
            if journal.forecast(receipt):new+=1
        enrolled=journal.records('forecast');old_settled=journal.records('settlement')
        for identity,f in enrolled.items():
            if digest(source_forecasts.get(identity))!=f['source_forecast_sha256']:raise ValueError('Enrolled source forecast changed')
            s=source_settlements.get(identity)
            if s is None:continue
            if identity in old_settled:
                if old_settled[identity]['source_settlement']!=s:raise ValueError('Source result changed')
                continue
            receipt={'type':'settlement','fixture_id':identity,'forecast_sha256':digest(f),'source_settlement':s,'recorded_at_utc':utcnow().isoformat()}
            if journal.settlement(receipt):settled+=1
        status={'run_id':run_id,'state':'collected','finished_at_utc':utcnow().isoformat(),'new_forecasts':new,'new_settlements':settled,
            'source15_finished_at_utc':source_report['status']['finished_at_utc'],'source15_events_sha256':source_checkpoint['events_sha256'],
            'github_run_id':os.environ.get('GITHUB_RUN_ID')}
        journal.run(status);seal(journal,status,prior,source_checkpoint,lifetime)
        print(json.dumps(status,ensure_ascii=False))
    except BaseException as error:
        write(STATE/'last_error.json',{'at_utc':utcnow().isoformat(),'error':str(error),'traceback':traceback.format_exc()})
        # Retain the verified source prefix on failure; do not adopt an invalid one.
        old_source={'event_count':checkpoint['source_event_count'],'events_sha256':checkpoint['source_events_sha256']}
        seal(journal,{'run_id':run_id,'state':'collection_failed','finished_at_utc':utcnow().isoformat(),'error':str(error)},prior,old_source,lifetime)
        raise
    finally:journal.close();lock.unlink()


def main():
    if sys.argv[1]=='verify':print('Verified',verify()[0]['event_count'],'comparison events')
    elif sys.argv[1]=='collect':collect()
    elif sys.argv[1]=='health':
        verify()
        if read(STATE/'report.json')['status']['state']!='collected':raise ValueError('Comparison needs attention')
    else:raise ValueError('Unknown command')


if __name__=='__main__':main()
