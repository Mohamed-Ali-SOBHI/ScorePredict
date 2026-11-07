"""Per-fixture archive eligibility, including propagation through prematch Elo.

No result or estimated sporting statistic is inserted into the model history.
Only fixtures whose entire feature dependency is unaffected may be scored.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = {
    'Bundesliga': ('bundesliga-2026-11-01.json', 'a0550893f3225d5d4e32a34a21faab0484f8f835548668f61c58b619daa06646'),
    'EPL': ('epl-2026-11-01.json', 'ecb6d86473d5a8bd9ac3a0edc76091bde66e9de4a69784f2a2941303cf5e1a71'),
}


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def archived(league):
    name, expected = ARCHIVES[league]
    body = (ROOT / 'production/recovery' / name).read_bytes()
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError('Manual archive hash mismatch')
    return json.loads(body)


def eligible(scope, home, away, cutoff, availability_hours=2):
    from inference.espn_results import team_name
    affected = set()
    missing = []
    for event in sorted(scope['events'], key=lambda e: e['kickoff']):
        if stamp(event['kickoff']) + timedelta(hours=availability_hours) > stamp(cutoff):
            continue
        clubs = {event['home'], event['away']}
        if not event['available']:
            affected.update(clubs)
            missing.append(event)
        elif affected & clubs:
            # Their later opponents inherit an uncertain Elo, even when their
            # own xG history is complete. Never silently ignore that dependency.
            affected.update(clubs)
    blocked = sorted(affected & {team_name(home), team_name(away)})
    return dict(eligible=not blocked, blockedTeams=blocked, cutoff=stamp(cutoff).isoformat(),
                missingMatches=missing, affectedTeams=sorted(affected))


def read_scope(path, league):
    scope = json.loads(Path(path).read_text(encoding='utf8'))
    age = datetime.now(timezone.utc) - stamp(scope['checkedAt'])
    if scope['league'] != league or scope['archiveSha256'] != ARCHIVES[league][1]:
        raise ValueError('Manual scope/archive mismatch')
    if not timedelta(0) <= age <= timedelta(minutes=30):
        raise ValueError('Manual completeness audit expired')
    return scope


def prepare(league, folder):
    import requests
    from inference.espn_results import LEAGUES, team_name
    from data_pipeline.scrapper import normalize_understat_teams, extract_stats_from_data, update_stats_with_opponents
    from data_pipeline.audit_club_coverage import audit_league
    payload = archived(league)
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if now - stamp(payload['captured_at']) > timedelta(days=10):
        raise ValueError('Manual recovery limited to ten days; review archive again')
    def event_key(home, away, kickoff):
        return stamp(kickoff).date().isoformat(), team_name(home), team_name(away)
    events = {}
    for game in payload['dates']:
        key = event_key(game['h']['title'], game['a']['title'], game['datetime'])
        if key in events:
            raise ValueError('Duplicate archived match')
        events[key] = dict(home=key[1], away=key[2], kickoff=stamp(game['datetime']).isoformat(),
                           available=game['isResult'] is True, goals=game['goals'])
    metadata = []
    def fetch(job):
        name, url = job
        response = requests.get(url, timeout=30); response.raise_for_status()
        (folder / name).write_bytes(response.content)
        return name, response, dict(url=url, sha256=hashlib.sha256(response.content).hexdigest(),
                                   retrievedAt=datetime.now(timezone.utc).isoformat())
    start = stamp(payload['captured_at']).date()
    days = [start + timedelta(days=d) for d in range((now.date()-start).days+1)]
    code = 'D1' if league == 'Bundesliga' else 'E0'
    jobs = [(league+'-results.csv', f'https://www.football-data.co.uk/mmz4281/2627/{code}.csv')]
    jobs += [(league+'-'+d.strftime('%Y%m%d')+'.json',
              f'https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUES[league]}/scoreboard?dates={d:%Y%m%d}&limit=100') for d in days]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(fetch, jobs))
    fd_rows = list(csv.DictReader(io.StringIO(fetched[0][1].content.decode('utf-8-sig'))))
    current_keys = set()
    for row in fd_rows:
        if row.get('FTHG', '') == '':
            continue
        day = datetime.strptime(row['Date'], '%d/%m/%Y').date().isoformat()
        key = (day, team_name(row['HomeTeam']), team_name(row['AwayTeam']))
        if key in current_keys:
            raise ValueError('Duplicate independent result')
        current_keys.add(key)
        old = events.get(key)
        if old and old['available'] and (int(old['goals']['h']), int(old['goals']['a'])) != (int(row['FTHG']), int(row['FTAG'])):
            raise ValueError('Independent result conflicts with archive')
        if not old:
            # Date-only result: conservative midnight cutoff, never fabricate a time.
            events[key] = dict(home=key[1], away=key[2], kickoff=day+'T00:00:00+00:00', available=False,
                               goals={'h': row['FTHG'], 'a': row['FTAG']})
    if any(e['available'] and key not in current_keys for key, e in events.items()):
        raise ValueError('Independent result feed does not confirm the archived history')
    for name, response, meta in fetched:
        metadata.append(meta)
        if name.endswith('.csv'):
            continue
        content = response.json()
        if not isinstance(content.get('events'), list):
            raise ValueError('Invalid independent scoreboard')
        for event in content['events']:
            for competition in event['competitions']:
                sides = {c['homeAway']: c for c in competition['competitors']}
                if set(sides) != {'home', 'away'}:
                    raise ValueError('Ambiguous scoreboard clubs')
                h, a = sides['home'], sides['away']
                kickoff = competition.get('date') or event['date']
                key = event_key(h['team']['displayName'], a['team']['displayName'], kickoff)
                old = events.get(key)
                status = (competition.get('status') or event['status'])['type']
                if old and old['available'] and status.get('completed') is True:
                    if (int(old['goals']['h']), int(old['goals']['a'])) != (int(h['score']), int(a['score'])):
                        raise ValueError('Scoreboard/archive result conflict')
                if not old:
                    events[key] = dict(home=key[1], away=key[2], kickoff=stamp(kickoff).isoformat(), available=False,
                                       goals={'h': h.get('score'), 'a': a.get('score')})
    data = {league+' 2026': normalize_understat_teams(payload)}
    stats = update_stats_with_opponents(extract_stats_from_data(data), data)
    registry = [dict(team_id=k, team_name=t['title']) for k,t in data[league+' 2026'].items()]
    integrity = audit_league(payload, registry, [r for rows in stats.values() for r in rows], league=league,
                            season=2026, expected_count=18 if league=='Bundesliga' else 20)
    if integrity['errors']:
        raise ValueError('Incomplete archive sporting fields: '+str(integrity['errors']))
    scope = dict(league=league, archiveSha256=ARCHIVES[league][1], capturedAt=payload['captured_at'],
                 checkedAt=datetime.now(timezone.utc).isoformat(), sources=metadata, events=list(events.values()),
                 integrity=integrity)
    path = folder / (league+'-scope.json')
    path.write_text(json.dumps(scope, ensure_ascii=False, indent=2), encoding='utf8')
    return path
