"""Collect, freeze, settle and report the isolated prospective paper experiment."""
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import csv,gzip,hashlib,html,io,json,math,os,shutil,subprocess,sys,traceback
from paper_core import MEMBERS,Journal,utcnow,stamp,canonical,digest,decisions,allocations,performance
ROOT=Path(__file__).resolve().parent
STATE=Path(os.environ.get('PAPER_STATE_DIR',str(ROOT/'state'))).resolve()
CACHE=Path(os.environ.get('RUNNER_TEMP',str(ROOT/'cache')))/'paper-source-cache'
GH=shutil.which('gh') or 'gh'
REPOSITORY='Mohamed-Ali-SOBHI/ScorePredict'
PRODUCTION='production_draw_pooled_unweighted_2026_09_05'
LEAGUES={'Bundesliga':'D1','EPL':'E0','Ligue_1':'F1','Serie_A':'I1'}

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(tmp,path)

def check_registration():
    registration=json.loads((ROOT/'registration.json').read_text(encoding='utf8'))
    for name,expected in registration['frozen_sha256'].items():
        path=ROOT/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Frozen code/model changed: '+name)
    return registration

def gh(*args):
    r=subprocess.run([GH,*args],capture_output=True,text=True,encoding='utf8',timeout=120)
    if r.returncode:raise RuntimeError('GitHub read failed: '+r.stderr[:350])
    return r.stdout

def production_snapshot(registration):
    runs=json.loads(gh('run','list','--repo',REPOSITORY,'--workflow','daily-predictions.yml','--status','success','--limit','1','--json','databaseId,headSha,createdAt,updatedAt'))
    if not runs:raise ValueError('No successful production snapshot')
    run=runs[0];rid=str(run['databaseId']);destination=CACHE/rid
    marker=destination/'verified_files.json'
    if not marker.exists():
        destination.mkdir(parents=True,exist_ok=True)
        listing=json.loads(gh('api',f'repos/{REPOSITORY}/actions/runs/{rid}/artifacts'))['artifacts']
        available=[a for a in listing if a['name'].startswith('scorepredict-strategy-evidence-') and not a['expired']]
        if not available:raise ValueError('No retained strategy evidence for latest successful run')
        artifact=max(available,key=lambda a:a['id'])
        gh('run','download',rid,'--repo',REPOSITORY,'--name',artifact['name'],'--dir',str(destination))
        files={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
        write(marker,files)
    hashes=json.loads(marker.read_text(encoding='utf8'))
    for name,value in hashes.items():
        if hashlib.sha256((destination/name).read_bytes()).hexdigest()!=value:raise ValueError('Downloaded source snapshot altered')
    def find(name):
        paths=[p for p in destination.rglob(name) if 'shadow' not in p.relative_to(destination).parts]
        if len(paths)!=1:raise ValueError('Missing/ambiguous evidence file: '+name)
        return paths[0]
    manifest=find('manifest.json')
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=registration['production_manifest_sha256']:raise ValueError('Production policy changed; review experiment comparator before continuing')
    return run,find('sportytrader_upcoming_portfolio_odds.csv'),find('live_portfolio_bet_log.csv'),hashes

def collect(batch):
    import requests
    jobs=[('fixtures','https://www.football-data.co.uk/fixtures.csv')]
    jobs += [(league,f'https://understat.com/getLeagueData/{league}/2026') for league in LEAGUES]
    def fetch(job):
        name,url=job
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0 (ScorePredict paper simulation)','X-Requested-With':'XMLHttpRequest'},timeout=40)
        response.raise_for_status();body=response.content;at=utcnow().isoformat()
        filename=name+('.csv.gz' if name=='fixtures' else '.json.gz');(batch/filename).write_bytes(gzip.compress(body,mtime=0))
        meta={'url':url,'retrieved_at_utc':at,'sha256':hashlib.sha256(body).hexdigest(),'file':filename,
              'http_date':response.headers.get('Date'),'last_modified':response.headers.get('Last-Modified')}
        value=list(csv.DictReader(io.StringIO(body.decode('utf-8-sig')))) if name=='fixtures' else response.json()
        return name,value,meta
    with ThreadPoolExecutor(max_workers=5) as pool:items=list(pool.map(fetch,jobs))
    sources={name:value for name,value,_ in items};metadata={name:meta for name,_,meta in items}
    write(batch/'sources.json',metadata);return sources,metadata

def triplet(row,prefix):
    try:
        q={o:float(row.get(prefix+s,'')) for o,s in [('away','A'),('draw','D'),('home','H')]}
        return q if all(math.isfinite(v) and v>1 for v in q.values()) else None
    except (TypeError,ValueError):return None

def identify_candidates(sources,catalog_path):
    from paper_models import normalize_team_name
    catalog=list(csv.DictReader(catalog_path.open(encoding='utf-8-sig')))
    candidates=[];rejections=[]
    for row in sources['fixtures']:
        league=next((l for l,code in LEAGUES.items() if row.get('Div')==code),None)
        if not league:continue
        home=normalize_team_name(row.get('HomeTeam',''));away=normalize_team_name(row.get('AwayTeam',''))
        from datetime import datetime
        day=datetime.strptime(row['Date'],'%d/%m/%Y').date()
        tag={'league':league,'home':row['HomeTeam'],'away':row['AwayTeam'],'provider_day':day.isoformat()}
        matches=[r for r in catalog if r.get('league')==league and r.get('schedule_source')=='sportytrader_jsonld_utc'
            and r.get('fixture_id') and r.get('kickoff_utc')
            and normalize_team_name(r.get('home_team',''))==home and normalize_team_name(r.get('away_team',''))==away
            and abs((stamp(r['kickoff_utc']).date()-day).days)<=1]
        if len(matches)!=1:rejections.append({**tag,'reason':'canonical_schedule_missing_or_ambiguous'});continue
        cat=matches[0];kickoff=stamp(cat['kickoff_utc']);remaining=kickoff-utcnow()
        if not timedelta(minutes=5)<=remaining<=timedelta(hours=24):rejections.append({**tag,'reason':'outside_5min_24h_window'});continue
        games=[g for g in sources[league]['dates'] if normalize_team_name(g['h']['title'])==home and normalize_team_name(g['a']['title'])==away
               and abs((datetime.fromisoformat(g['datetime']).date()-kickoff.date()).days)<=1]
        if len(games)!=1 or games[0]['isResult'] is not False:rejections.append({**tag,'reason':'understat_fixture_not_unique_pending'});continue
        game=games[0];quotes={book:triplet(row,book) for book in ['B365','Avg','BW','WH']}
        if quotes['B365'] is None or (league=='Serie_A' and quotes['Avg'] is None):rejections.append({**tag,'reason':'required_same_provider_triplet_missing'});continue
        candidates.append({'fixture_id':'understat:'+str(game['id']),'production_fixture_id':cat['fixture_id'],'league':league,
            'home_id':str(game['h']['id']),'away_id':str(game['a']['id']),'home_team':game['h']['title'],'away_team':game['a']['title'],
            'kickoff_utc':kickoff.isoformat(),'schedule_source':'sportytrader_jsonld_utc','quotes':quotes})
    if len({c['fixture_id'] for c in candidates})!=len(candidates):raise ValueError('Duplicate eligible fixture')
    return candidates,rejections

def observed_reference(fixture,rows):
    options=[]
    for r in rows:
        if r.get('portfolio_name')!=PRODUCTION or r.get('fixture_id')!=fixture['production_fixture_id']:continue
        if r.get('recommended','').lower() in ['false','0']:continue
        created=stamp(r['prediction_generated_at_utc']);kickoff=stamp(fixture['kickoff_utc'])
        if created>=kickoff or created>utcnow():raise ValueError('Non-prospective reference source')
        options.append((created,r))
    if not options:return None
    latest=max(t for t,_ in options);rows=[r for t,r in options if t==latest]
    terms={(r['selected_outcome'],float(r['selected_odds'])) for r in rows}
    if len(terms)!=1:raise ValueError('Conflicting current production tickets')
    outcome,odds=next(iter(terms));outcome={'away_win':'away','home_win':'home'}.get(outcome,outcome)
    return {'outcome':outcome,'odds':odds,'generated_at_utc':latest.isoformat(),'source':'published_production_artifact','snapshot_keys':[r['snapshot_key'] for r in rows]}

def settle(journal,sources,metadata):
    forecasts=journal.records('forecast');settled=journal.records('settlement');new=0;issues=[]
    for identity,f in forecasts.items():
        league=f['league'];games=[g for g in sources[league]['dates'] if 'understat:'+str(g['id'])==identity]
        if len(games)!=1:issues.append({'fixture_id':identity,'reason':'result_fixture_missing'});continue
        game=games[0]
        if game['isResult'] is not True:continue
        kickoff=stamp(f['kickoff_utc']);seen=stamp(metadata[league]['retrieved_at_utc'])
        if seen<kickoff+timedelta(hours=2):continue
        # Understat dates have no explicit timezone; this check only quarantines discrepancies.
        sporting_time=stamp(game['datetime'].replace(' ','T')+'+00:00')
        if abs((sporting_time-kickoff).total_seconds())>1800:
            issues.append({'fixture_id':identity,'reason':'schedule_changed_or_timezone_discrepancy_requires_review'});continue
        if str(game['h']['id'])!=f['home_id'] or str(game['a']['id'])!=f['away_id']:
            issues.append({'fixture_id':identity,'reason':'changed_teams_requires_review'});continue
        h,a=int(game['goals']['h']),int(game['goals']['a'])
        if min(h,a)<0:raise ValueError('Invalid score')
        outcome='home' if h>a else 'away' if h<a else 'draw'
        if identity in settled:
            if settled[identity]['outcome']!=outcome or settled[identity]['home_goals']!=h or settled[identity]['away_goals']!=a:
                issues.append({'fixture_id':identity,'reason':'source_result_revision_requires_review'})
            continue
        s={'forecast_sha256':digest(f),'outcome':outcome,'home_goals':h,'away_goals':a,
           'result_seen_at_utc':seen.isoformat(),'source_url':metadata[league]['url'],'source_snapshot_sha256':metadata[league]['sha256']}
        if journal.append('settlement',identity,s):new+=1
    return new,issues

def make_report(journal,status):
    f=journal.records('forecast');s=journal.records('settlement');rows=performance(f,s)
    write(STATE/'report.json',{'status':status,'registered_at_utc':journal.registration['registered_at_utc'],
        'forecasts':len(f),'settled_fixtures':len(s),'portfolios':rows,'production_changed':False})
    write(STATE/'evidence.json',{'registration_sha256':journal.registration_hash,'events':journal.export()})
    with (STATE/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    def fmt(v):return '—' if v is None else f'{v:.2f}'.replace('.',',')
    trs=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['label'],r['committed_bets'],r['settled_bets'],r['pending_bets'],fmt(r['settled_stake']),fmt(r['profit']),fmt(None if r['roi'] is None else r['roi']*100),fmt(r['max_daily_drawdown']),fmt(r['additional_profit'])])+'</tr>' for r in rows)
    receipt_rows=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['home_team']+' – '+r['away_team'],r['kickoff_utc'],r['recorded_at_utc'],', '.join(c['member'] for c in r['decisions'] if c['selected']) or 'Aucun',s[k]['outcome'] if k in s else 'En attente'])+'</tr>' for k,r in f.items())
    body=f'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Suivi en simulation des six stratégies</title><style>body{{font:15px/1.6 system-ui;margin:0;color:#173d2c;background:#f3f7f4}}main{{max-width:1350px;margin:auto;padding:30px 18px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #d9e3dc}}a{{color:#185f42}}</style><main>
<h1>Suivi prospectif en simulation</h1><p>Début : {html.escape(journal.registration['registered_at_utc'])}. Dernière collecte : {html.escape(status['finished_at_utc'])}. <strong>Aucune modification de production ; aucune mise réelle.</strong></p>
<p>{len(f)} matchs avec décisions enregistrées avant le coup d’envoi ; {len(s)} résultats confirmés. État de la collecte : {html.escape(status['state'])}. Les anciennes simulations historiques ne sont pas intégrées à ce suivi.</p>
<h2>Comparaison des portefeuilles</h2><p>Référence : recommandations de production observées au moment de la première capture admissible, sur les mêmes matchs que les challengers. Les révisions ultérieures de production ne réécrivent pas cette référence. Mise de référence : 1 unité ; ajouts : 1 ou 0,5 selon la ligne. L’union donne toujours priorité à la référence, puis à l’ordre figé des six stratégies.</p>
<div class="scroll"><table><tr><th>Portefeuille</th><th>Paris enregistrés</th><th>Terminés</th><th>En attente</th><th>Mises réglées</th><th>Gain net</th><th>Rendement %</th><th>Baisse max quotidienne</th><th>Gain des ajouts</th></tr>{trs}</table></div>
<p>Les pertes maximales sont calculées sur les gains réglés, regroupés par jour de coup d’envoi. Les paris encore en attente n’y sont pas inclus ; leur exposition figure dans le fichier détaillé. Plus de paris signifie davantage de mises : comparer aussi le rendement par unité misée.</p>
<h2>Prédictions figées</h2><div class="scroll"><table><tr><th>Match</th><th>Coup d’envoi UTC</th><th>Enregistrement UTC</th><th>Stratégies ayant retenu le match</th><th>Résultat</th></tr>{receipt_rows}</table></div>
<h2>Règles de collecte</h2><p>Première capture complète entre 24 heures et 5 minutes avant un horaire vérifié. Les cotes Bet365 proviennent du fichier périodique Football-Data : leur collecte est horodatée, leur disponibilité réelle chez le bookmaker n’est pas certifiée. Les caractéristiques sportives restent calculées avec une coupure à J−3. Modèles et filtres sont figés ; aucun entraînement ni activation automatique.</p>
<p>Les décisions, y compris les abstentions, sont conservées dans un journal append-only avec empreintes des modèles, données et entrées. Les enregistrements sont horodatés sur le runner GitHub et associés à l’exécution correspondante. Les matchs sans données suffisantes sont exclus et consignés dans les diagnostics. Un changement d’horaire ou de résultat est signalé pour examen.</p>
<p><a href="registration.json">Protocole figé</a> · <a href="comparison.csv">Comparaison complète</a> · <a href="report.json">Statut et métriques</a> · <a href="evidence.json">Journal des preuves</a></p></main></html>'''
    (STATE/'rapport.html').write_text(body,encoding='utf8')

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise ValueError('Live simulation runs on GitHub Actions only')
    registration=check_registration()
    # Prevent overlapping collectors. Never remove an existing lock automatically.
    if not (STATE/'journal.sqlite3').is_file():raise ValueError('Persistent journal missing; refusing to start an empty history')
    lock=STATE/'collector.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    journal=None
    try:
        import numpy,pandas,sklearn,xgboost
        for module in [numpy,pandas,sklearn,xgboost]:
            if module.__version__!=registration['runtime'][module.__name__]:raise ValueError('Model runtime changed: '+module.__name__)
        started=utcnow();runid=started.strftime('%Y%m%dT%H%M%S%fZ');batch=STATE/'captures'/runid;batch.mkdir(parents=True)
        journal=Journal(STATE/'journal.sqlite3',registration)
        print('Paper capture started',runid,flush=True)
        run,catalog,baseline_file,artifacthashes=production_snapshot(registration)
        sources,metadata=collect(batch)
        write(batch/'production_source.json',{'run':run,'artifact_sha256':artifacthashes})
        (batch/'production_bet_log.csv.gz').write_bytes(gzip.compress(baseline_file.read_bytes(),mtime=0))
        (batch/'production_fixtures.csv.gz').write_bytes(gzip.compress(catalog.read_bytes(),mtime=0))
        if not stamp('2026-07-01T00:00:00Z')<=started<stamp('2027-07-01T00:00:00Z'):raise ValueError('Frozen experiment requires season review; no automatic migration')
        candidates,rejected=identify_candidates(sources,catalog)
        if utcnow()-stamp(run['updatedAt'])>timedelta(hours=24):
            rejected += [{'fixture_id':c['fixture_id'],'reason':'production_snapshot_older_than_24h'} for c in candidates];candidates=[]
        forecasts=journal.records('forecast');candidates=[c for c in candidates if c['fixture_id'] not in forecasts]
        new=0
        if candidates:
            from paper_models import Models,current_history,frame_for_fixture,OUTCOMES
            from threadpoolctl import threadpool_limits
            history=current_history({k:v for k,v in sources.items() if k in LEAGUES});models=Models()
            baseline_rows=list(csv.DictReader(baseline_file.open(encoding='utf-8-sig')))
            for fixture in candidates:
                try:
                    frame,audit=frame_for_fixture(history,fixture,fixture['quotes'],utcnow())
                    names=list(dict.fromkeys(m['model'] for m in MEMBERS if m['league']==fixture['league']))
                    with threadpool_limits(limits=2):probabilities,vectors=models.score(frame,names)
                    p={name:dict(zip(OUTCOMES,map(float,values[0]))) for name,values in probabilities.items()}
                    reference=observed_reference(fixture,baseline_rows);choices=decisions(fixture['league'],p,fixture['quotes']['B365'])
                    inputs={name:{k:(float(v) if pandas.notna(v) else None) for k,v in vector.iloc[0].items()} for name,vector in vectors.items()}
                    receipt={k:v for k,v in fixture.items() if k!='quotes'}
                    receipt.update({'recorded_at_utc':utcnow().isoformat(),'registration_sha256':digest(registration),
                        'quotes_collected_at_utc':metadata['fixtures']['retrieved_at_utc'],
                        'sports_collected_at_utc':metadata[fixture['league']]['retrieved_at_utc'],
                        'production_snapshot_completed_at_utc':run['updatedAt'],'production_run_id':run['databaseId'],
                        'source_snapshot_sha256':{k:m['sha256'] for k,m in metadata.items()},'capture_directory':batch.relative_to(STATE).as_posix(),
                        'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
                        'odds':fixture['quotes']['B365'],'all_pre_triplets':fixture['quotes'],
                        'probabilities':p,'features':inputs,'history_audit':audit,'reference':reference,
                        'decisions':choices,'portfolios':allocations(reference,choices)})
                    if journal.append('forecast',fixture['fixture_id'],receipt):new+=1
                except (ValueError,KeyError) as error:
                    rejected.append({'fixture_id':fixture['fixture_id'],'reason':'capture_rejected','detail':str(error)})
        settled,issues=settle(journal,sources,metadata)
        write(batch/'rejections.json',rejected);write(batch/'settlement_issues.json',issues)
        age=(utcnow()-stamp(run['updatedAt'])).total_seconds()/3600
        state='review_required' if issues else 'capture_incomplete' if any(r['reason']=='capture_rejected' for r in rejected) else 'production_source_stale' if age>24 else 'collected'
        status={'run_id':runid,'started_at_utc':started.isoformat(),'finished_at_utc':utcnow().isoformat(),
            'state':state,'production_snapshot_age_hours':age,'new_forecasts':new,'new_settlements':settled,
            'eligible_new_candidates':len(candidates),'rejected_rows':len(rejected),'settlement_issues':issues,
            'production_run_id':run['databaseId'],'github_run_id':os.environ.get('GITHUB_RUN_ID'),
            'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'production_changed':False}
        journal.append('run',runid,status);journal.verify();write(STATE/'last_run.json',status);make_report(journal,status)
        print(json.dumps(status,ensure_ascii=False),flush=True)
    except BaseException as error:
        write(STATE/'last_error.json',{'at_utc':utcnow().isoformat(),'error':str(error),'traceback':traceback.format_exc(),
              'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'production_changed':False})
        raise
    finally:
        if journal is not None:journal.db.close()
        lock.unlink()

if __name__=='__main__':main()
