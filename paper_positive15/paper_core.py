"""Append-only prospective decisions and paired paper portfolios. No external writes."""
from datetime import datetime,timezone,timedelta
import hashlib,json,math,sqlite3

from pathlib import Path
MEMBERS=json.loads((Path(__file__).parent/'members.json').read_text(encoding='utf8'))

def utcnow():return datetime.now(timezone.utc)
def stamp(value):
    t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('Explicit timezone required')
    return t.astimezone(timezone.utc)
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def portfolio_specs():
    additions=[m['id'] for m in MEMBERS[1:]]
    specs=[{'id':'reference','label':'Nuls Bundesliga seuls','members':[],'baseline':True,'addition_stake':0},
        {'id':'bundesliga_plus15','label':'Nuls Bundesliga + 15 ajouts (union sans doublon)','members':additions,'baseline':True,'addition_stake':1}]
    for m in MEMBERS[1:]:
        specs += [{'id':'alone_'+m['id'],'label':m['label']+' seule','members':[m['id']],'baseline':False,'addition_stake':1},
                  {'id':'reference_'+m['id'],'label':'Bundesliga + '+m['label'],'members':[m['id']],'baseline':True,'addition_stake':1}]
    return specs

def decisions(league,probabilities,odds,context=None):
    if set(odds)!={'away','draw','home'} or any(not math.isfinite(v) or v<=1 for v in odds.values()):raise ValueError('Invalid complete odds triplet')
    selected=[]
    for member in MEMBERS:
        if member['league']!=league:continue
        p=probabilities[member['model']]
        if set(p)!={'away','draw','home'} or any(not math.isfinite(v) or not 0<=v<=1 for v in p.values()) or abs(sum(p.values())-1)>1e-6:raise ValueError('Invalid probabilities')
        o=member['outcome'];ev=p[o]*odds[o]*.98-1
        profile=member['profile'];gate=True
        if profile!='all':
            if context is None:raise ValueError('Missing frozen filter context')
            if profile=='balanced_market':
                gate=abs(context['q_home']-context['q_away'])<=.15
            elif profile=='low_goal_parity':
                gap=context['xg_gap_abs'];total=context['xg_total']
                gate=gap is not None and total is not None and gap<=.5 and total<=3.
            else:raise ValueError('Unknown frozen profile')
        selected.append({'member':member['id'],'outcome':o,'odds':odds[o],'probability':p[o],
            'ev_after_2pct':ev,'selected':bool(1.2<=odds[o]<=10 and ev>member['threshold'] and gate)})
    return selected

def allocations(reference,choices):
    if reference is not None:
        if reference['outcome'] not in ['away','draw','home'] or not math.isfinite(reference['odds']) or reference['odds']<=1:raise ValueError('Invalid reference bet')
    byid={c['member']:c for c in choices};output={}
    for spec in portfolio_specs():
        if spec['baseline'] and reference is not None:
            output[spec['id']]={'source':'reference','outcome':reference['outcome'],'odds':reference['odds'],'stake':1.}
            continue
        eligible=[byid[m] for m in spec['members'] if m in byid and byid[m]['selected']]
        output[spec['id']]=None if not eligible else {'source':eligible[0]['member'],'outcome':eligible[0]['outcome'],
            'odds':eligible[0]['odds'],'stake':float(spec['addition_stake'])}
    return output

def validate_receipt(receipt,registered,now):
    kickoff=stamp(receipt['kickoff_utc']);created=stamp(receipt['recorded_at_utc'])
    if not stamp(registered)<=created<=now or not timedelta(minutes=5)<=kickoff-now<=timedelta(hours=24):raise ValueError('Outside prospective capture window')
    for key in ['quotes_collected_at_utc','sports_collected_at_utc','production_snapshot_completed_at_utc']:
        if stamp(receipt[key])>created:raise ValueError('Unavailable input')
    if created-stamp(receipt['quotes_collected_at_utc'])>timedelta(minutes=30):raise ValueError('Quote retrieval too old')
    if created-stamp(receipt['production_snapshot_completed_at_utc'])>timedelta(hours=24):raise ValueError('Production snapshot too old')
    reference=receipt['reference']
    if reference is not None and not stamp(reference['generated_at_utc'])<=created<kickoff:raise ValueError('Late reference')
    expected=decisions(receipt['league'],receipt['probabilities'],receipt['odds'],receipt.get('filter_context'))
    anchor=next((c for c in expected if c['member']=='Bundesliga_anchor' and c['selected']),None)
    if (anchor is None)!=(reference is None):raise ValueError('Reference differs from frozen Bundesliga anchor')
    if anchor is not None and (reference['outcome']!=anchor['outcome'] or reference['odds']!=anchor['odds']):raise ValueError('Changed reference terms')
    if expected!=receipt['decisions'] or allocations(reference,expected)!=receipt['portfolios']:raise ValueError('Altered portfolio decisions')

class Journal:
    def __init__(self,path,registration):
        self.registration=registration;self.registration_hash=digest(registration)
        self.db=sqlite3.connect(path,timeout=5)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity TEXT NOT NULL,
            payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL, UNIQUE(kind,identity));
          CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'Immutable evidence'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'Immutable evidence'); END;
        ''')
        try:self.verify()
        except BaseException:
            self.db.close();raise
    def verify(self):
        prior=self.registration_hash
        for kind,identity,payload,previous,eventhash in self.db.execute('SELECT kind,identity,payload,previous_hash,event_hash FROM events ORDER BY seq'):
            data=json.loads(payload)
            if previous!=prior or digest({'kind':kind,'identity':identity,'payload':data,'previous_hash':previous})!=eventhash:raise ValueError('Evidence chain altered')
            prior=eventhash
    def records(self,kind):return {key:json.loads(payload) for key,payload in self.db.execute('SELECT identity,payload FROM events WHERE kind=? ORDER BY seq',(kind,))}
    def append(self,kind,identity,payload):
        if kind not in ['forecast','settlement','run']:raise ValueError('Unknown event type')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT payload FROM events WHERE kind=? AND identity=?',(kind,identity)).fetchone()
            if old:
                if canonical(json.loads(old[0]))!=canonical(payload):raise ValueError('Cannot replace immutable evidence')
                self.db.rollback();return False
            if kind=='forecast':
                if payload['fixture_id']!=identity or payload['registration_sha256']!=self.registration_hash:raise ValueError('Wrong fixture or registration')
                validate_receipt(payload,self.registration['registered_at_utc'],utcnow())
            if kind=='settlement':
                f=self.records('forecast').get(identity)
                if f is None:raise ValueError('Settlement without prior forecast')
                if payload['outcome'] not in ['away','draw','home']:raise ValueError('Unconfirmed outcome')
                now=utcnow();seen=stamp(payload['result_seen_at_utc'])
                if not stamp(f['kickoff_utc'])+timedelta(hours=2)<=seen<=now:raise ValueError('Result not yet available')
                if payload['forecast_sha256']!=digest(f):raise ValueError('Settlement refers to another forecast')
            row=self.db.execute('SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            prior=row[0] if row else self.registration_hash
            eventhash=digest({'kind':kind,'identity':identity,'payload':payload,'previous_hash':prior})
            self.db.execute('INSERT INTO events(kind,identity,payload,previous_hash,event_hash) VALUES(?,?,?,?,?)',
                (kind,identity,canonical(payload),prior,eventhash));self.db.commit();return True
        except BaseException:self.db.rollback();raise
    def export(self):
        return [{'seq':s,'kind':k,'identity':i,'payload':json.loads(p),'previous_hash':h,'event_hash':e}
            for s,k,i,p,h,e in self.db.execute('SELECT * FROM events ORDER BY seq')]

def performance(forecasts,settlements):
    rows=[]
    for spec in portfolio_specs():
        settled=[];pending=0;pendingstake=0;committed=0
        for key,f in forecasts.items():
            bet=f['portfolios'][spec['id']]
            if bet is None:continue
            committed+=1
            if key not in settlements:pending+=1;pendingstake+=bet['stake'];continue
            s=settlements[key];won=bet['outcome']==s['outcome']
            settled.append({'day':f['kickoff_utc'][:10],'stake':bet['stake'],
                'profit':bet['stake']*(bet['odds']*won-1),'won':won,'source':bet['source']})
        daily={}
        for r in settled:daily[r['day']]=daily.get(r['day'],0)+r['profit']
        high=equity=drawdown=0
        for day,pnl in sorted(daily.items()):equity+=pnl;high=max(high,equity);drawdown=max(drawdown,high-equity)
        stakes=sum(r['stake'] for r in settled)
        rows.append({'portfolio':spec['id'],'label':spec['label'],'committed_bets':committed,'settled_bets':len(settled),
            'pending_bets':pending,'pending_stake':pendingstake,'settled_stake':stakes,'wins':sum(r['won'] for r in settled),
            'profit':equity,'roi':equity/stakes if stakes else None,'max_daily_drawdown':drawdown,
            'additional_profit':sum(r['profit'] for r in settled if r['source']!='reference'),
            'additional_settled_bets':sum(r['source']!='reference' for r in settled)})
    baseline=rows[0]
    for r in rows:
        r['profit_difference_vs_reference']=r['profit']-baseline['profit']
        r['drawdown_difference_vs_reference']=r['max_daily_drawdown']-baseline['max_daily_drawdown']
    return rows
