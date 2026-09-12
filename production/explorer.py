"""Read-only, pre-match team statistics; never contributes to the bet ledger."""
import math
from datetime import datetime
from pathlib import Path

from inference.prediction_window import in_prediction_window


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def build_explorer(root: Path, rows: list[dict], now: datetime) -> dict:
    from production.dashboard import _read_csv, _parse_date, _kickoff, DISPLAY_TIMEZONE, LEAGUE_LABELS
    season = now.year if now.month >= 7 else now.year - 1
    teams = {}
    for league in LEAGUE_LABELS:
        for path in (root / 'Data' / league).glob(f'{season} *.csv'):
            for row in _read_csv(path):
                teams.setdefault((league, row.get('team_name')), {})[row.get('match_id')] = row

    def stats(league, name, cutoff):
        history = []
        for row in teams.get((league, name), {}).values():
            date = _parse_date(row.get('date'))
            # Compare calendar days conservatively: ambiguous source times cannot leak same-day results
            if date and date.date() < min(cutoff.date(), now.astimezone(DISPLAY_TIMEZONE).date()) and row.get('result') in {'w', 'd', 'l'}:
                history.append(row)
        history.sort(key=lambda row: row['date'])
        fields = {'goals':'team_goals', 'conceded':'opponent_goals', 'xg':'team_xG', 'xga':'opponent_xG', 'shots':'team_shots', 'xpoints':'team_xpts'}
        means = {}
        for label, column in fields.items():
            values = [numeric(r.get(column)) for r in history]
            means[label] = round(sum(values) / len(values), 2) if values and all(v is not None for v in values) else None
        return {'name': name, 'played':len(history), 'form':[r['result'] for r in history[-5:]], 'averages':means, 'asOf':history[-1]['date'][:10] if history else None}

    matches = {}
    for row in rows:
        date = _kickoff(row)
        if not date or not in_prediction_window(date, now):
            continue
        probabilities = [numeric(row.get(k)) for k in ('pred_home_win','pred_draw','pred_away_win')]
        if any(p is None or not 0 <= p <= 1 for p in probabilities) or abs(sum(probabilities)-1) > .02:
            continue
        league, home, away = row.get('league'), row.get('team_name'), row.get('opponent_name')
        key = (league, home, away, date[:10])
        matches.setdefault(key, {'date':date, 'league':league, 'leagueLabel':LEAGUE_LABELS.get(league,league), 'homeTeam':home, 'awayTeam':away, 'probabilities':probabilities, 'teams':[stats(league, home, _parse_date(date)), stats(league, away, _parse_date(date))]})
    return {'season':season, 'generatedAt':now.isoformat(), 'matches':sorted(matches.values(), key=lambda r:r['date'])}
