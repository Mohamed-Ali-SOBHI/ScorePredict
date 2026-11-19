"""One-off, explicitly authorised early publication; immutable ledger, no bets placed."""
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path
import gzip,hashlib,json,re,sys
import pandas as pd,requests
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'paper_positive15'),str(ROOT)]
from run_paper import check_registration
from paper_models import Models
from inference.price_only_inputs import price_frame
from inference.public_additions import qualifies,select_public_bets,ENGLAND_HOME
from inference.english_away_public import fixed_unit_stakes
from inference.live_tracking import build_tracking_rows,canonicalize_tracking_rows
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME
from inference.supabase_prediction_store import configuration,pull,remote_records,request_headers
from inference.espn_results import fetch_scoreboard,team_name
from production.understat_fallback import merge_snapshot,write

URL='https://www.wbookie.com/en/odds?date=2026-11-21'
TARGETS={('Aston Villa','Sunderland'):'sportytrader:8558913',('Bournemouth','Nottingham Forest'):'sportytrader:8558914'}
class Table(HTMLParser):
    def __init__(self):super().__init__();self.row=None;self.cell=None;self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,s):
        if self.cell is not None and s.strip():self.cell.append(s.strip())
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:self.row.append(' '.join(self.cell));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def collect(body,now):
    if now.date().isoformat()!='2026-11-19':raise ValueError('One-off run expired')
    text=body.decode('utf8');stamp=re.search(r'Updated\s+(\d{2}):(\d{2})',text)
    if not stamp or 'UK time (GMT+0)' not in text:raise ValueError('Quote timestamp/timezone unavailable')
    captured=now.replace(hour=int(stamp.group(1)),minute=int(stamp.group(2)),second=0,microsecond=0)
    if not timedelta(0)<=now-captured<=timedelta(minutes=45):raise ValueError('Quote feed stale or future-dated')
    t=Table();t.feed(text);headers=[r for r in t.rows if 'Match' in r and 'Bet365' in r]
    if len(headers)!=1:raise ValueError('Ambiguous bookmaker column')
    col=headers[0].index('Bet365');out={}
    for home,away in TARGETS:
        needle='1 · '+home+' X · Draw 2 · '+away
        rows=[r for r in t.rows if len(r)>col and r[1]==needle]
        if len(rows)!=1:raise ValueError('Fixture absent or ambiguous: '+home+' - '+away)
        q=[float(x) for x in rows[0][col].split()]
        if len(q)!=3 or min(q)<=1:raise ValueError('Incomplete bookmaker triplet')
        out[(home,away)]=dict(zip(('home','draw','away'),q))
    return out,captured

def collect_receipt(receipt,now):
    if receipt.get('source')!=URL or receipt.get('book')!='Bet365':raise ValueError('Unexpected receipt source')
    captured=datetime.fromisoformat(receipt['sourceUpdateUtc'])
    retrieved=datetime.fromisoformat(receipt['retrievedUtc'])
    if now.date().isoformat()!='2026-11-19' or not timedelta(0)<=now-captured<=timedelta(minutes=45) or not captured<=retrieved<=now:
        raise ValueError('Receipt stale or future-dated')
    if not re.fullmatch('[0-9a-f]{64}',receipt.get('sourceSha256','')):raise ValueError('Missing source digest')
    quotes={}
    for r in receipt['quotes']:
        identity=(r['home'],r['away']);q={k:float(r[k]) for k in ('home_odds','draw_odds','away_odds')}
        if identity not in TARGETS or identity in quotes or min(q.values())<=1:raise ValueError('Invalid receipt fixture or quote')
        quotes[identity]=dict(home=q['home_odds'],draw=q['draw_odds'],away=q['away_odds'])
    if set(quotes)!=set(TARGETS):raise ValueError('Incomplete receipt')
    return quotes,captured

def prepare(body,scoreboard,now,existing,receipt=None):
    quotes,captured=collect_receipt(receipt,now) if receipt is not None else collect(body,now)
    check_registration();model=Models();rows=[]
    for (home,away),identity in TARGETS.items():
        matches=scoreboard[(scoreboard.home_team_norm==team_name(home))&(scoreboard.away_team_norm==team_name(away))]
        if len(matches)!=1:raise ValueError('Independent fixture ambiguous: '+home)
        kickoff=pd.Timestamp(matches.iloc[0].official_date).tz_localize('Europe/Paris').tz_convert('UTC')
        if kickoff!=pd.Timestamp('2026-11-21T15:00:00Z') or kickoff<=pd.Timestamp(now)+pd.Timedelta(minutes=5):raise ValueError('Kickoff mismatch')
        q=quotes[(home,away)];frame=price_frame(q);probs,vectors=model.score(frame,['local_price_only']);p=float(probs['local_price_only'][0,2])
        if not qualifies(p,q['home']):raise ValueError('Quote no longer qualifies: '+home)
        qm=(1/q['home'])/sum(1/x for x in q.values());rows.append(dict(fixture_id=identity,kickoff_utc=kickoff.isoformat(),date=kickoff.tz_convert('Europe/Paris'),league='EPL',team_name=home,opponent_name=away,
            strategy_name=ENGLAND_HOME,strategy_names=ENGLAND_HOME,selected_outcome='home_win',selected_odds=q['home'],predicted_probability=p,raw_model_probability=p,
            market_probability=qm,edge=p-qm,value_score=p/qm,expected_value=p*q['home']*.98-1,raw_expected_value=p*q['home']-1,
            probability_note='manual_weekend_wbookie_20261119__B365__'+captured.isoformat(),train_max_season=2024,recommended_bet='home_win'))
    bets=select_public_bets(pd.DataFrame(rows),existing,DEFAULT_PORTFOLIO_NAME)
    if not existing.empty:
        active=existing[existing.portfolio_name.eq(DEFAULT_PORTFOLIO_NAME)]
        held={(team_name(r.team_name),team_name(r.opponent_name),pd.Timestamp(r.date).date().isoformat()) for r in active.itertuples()}
        bets=bets[[ (team_name(r.team_name),team_name(r.opponent_name),pd.Timestamp(r.date).date().isoformat()) not in held for r in bets.itertuples() ]]
    return fixed_unit_stakes(bets,2.5),captured

def main():
    from threadpoolctl import threadpool_limits
    now=datetime.now(timezone.utc);url,key=configuration()
    if not url or not key:raise ValueError('Permanent store is not configured')
    out=ROOT/'inference/output/understat_fallback';out.mkdir(parents=True,exist_ok=True)
    ledger_path=out/'manual_ledger.csv';status=out/'manual_status.json';pull(ledger_path,status,portfolio_name=DEFAULT_PORTFOLIO_NAME);existing=pd.read_csv(ledger_path)
    response=requests.get('https://mohamed-ali-sobhi.github.io/ScorePredict/data/dashboard.json',params={'manual':now.isoformat()},timeout=40);response.raise_for_status();dashboard=response.json()
    response=requests.get('https://mohamed-ali-sobhi.github.io/ScorePredict/data/explorer.json',params={'manual':now.isoformat()},timeout=40);response.raise_for_status();explorer=response.json()
    if dashboard.get('activity') and existing.empty:raise ValueError('Published history missing from permanent store')
    receipt=json.loads((ROOT/'production/recovery/weekend-2026-11-19.json').read_text(encoding='utf8'))
    with threadpool_limits(limits=2):bets,captured=prepare(None,fetch_scoreboard('EPL','2026-11-21'),now,existing,receipt=receipt)
    incoming=build_tracking_rows(bets,portfolio_name=DEFAULT_PORTFOLIO_NAME)
    combined=canonicalize_tracking_rows(pd.concat([existing,incoming],ignore_index=True)) if not incoming.empty else existing
    snapshot=merge_snapshot(dashboard,combined,now)
    snapshot['meta']['serviceNotice']='Cotes Bet365 relevées le 19 novembre via WBookie ; elles peuvent évoluer. Statistiques Understat indisponibles : stratégies sportives en pause.'
    expected={r.team_name for r in incoming.itertuples()}
    seen={p['homeTeam'] for p in snapshot.get('predictions',[]) if p.get('earlyPublished') is True}
    if not expected.issubset(seen):raise ValueError('Early selections missing from snapshot')
    if incoming.empty:print('No new bets; prior publications preserved')
    else:
        payload=remote_records(incoming)
        res=requests.post(f'{url}/rest/v1/prediction_history',headers=request_headers(key,upsert=True),params={'on_conflict':'snapshot_key'},json=payload,timeout=30);res.raise_for_status()
    write(ROOT/'production/static/data/dashboard.json',snapshot)
    write(ROOT/'production/static/data/explorer.json',explorer)
    write(out/'manual-weekend-report.json',dict(source=URL,sourceUpdateUtc=captured.isoformat(),retrievedAt=receipt['retrievedUtc'],sha256=receipt['sourceSha256'],selected=sorted(expected),newBets=len(incoming),unit=1))
    print('Manual weekend selections:',sorted(expected))
if __name__=='__main__':main()
