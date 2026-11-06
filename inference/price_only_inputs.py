"""Temporary, sports-free inputs for the already published EPL home model only."""
import csv
from datetime import datetime

import numpy as np
import pandas as pd

from data_pipeline.market_data import normalize_team_name
from train.make_dataset import add_market_implied_features


def price_frame(quotes):
    odds = [quotes[key] for key in ('home', 'draw', 'away')]
    if not np.isfinite(odds).all() or not (np.asarray(odds) > 1).all():
        raise ValueError('A complete same-bookmaker odds triplet is required')
    frame = pd.DataFrame([dict(zip(
        ['market_home_win_odds_open', 'market_draw_odds_open', 'market_away_win_odds_open'], odds))])
    frame['league'] = 'EPL'
    return add_market_implied_features(frame)


def identify_price_candidates(fixtures, catalog_path, now):
    """Cross-check two existing sources, without pretending to have Understat IDs."""
    with catalog_path.open(encoding='utf-8-sig') as stream:
        catalog = list(csv.DictReader(stream))
    candidates, rejected = [], []
    for row in fixtures:
        if row.get('Div') != 'E0':
            continue
        tag = dict(home=row.get('HomeTeam'), away=row.get('AwayTeam'))
        try:
            day = datetime.strptime(row['Date'], '%d/%m/%Y').date()
            home, away = [normalize_team_name(row[k]) for k in ('HomeTeam', 'AwayTeam')]
            matches = [c for c in catalog if c.get('league') == 'EPL'
                       and c.get('schedule_source') == 'sportytrader_jsonld_utc'
                       and c.get('fixture_id') and c.get('kickoff_utc')
                       and normalize_team_name(c['home_team']) == home
                       and normalize_team_name(c['away_team']) == away
                       and abs((pd.Timestamp(c['kickoff_utc']).date() - day).days) <= 1]
            if len(matches) != 1:
                raise ValueError('canonical_schedule_missing_or_ambiguous')
            cat = matches[0]
            kickoff = pd.Timestamp(cat['kickoff_utc'])
            if kickoff.tzinfo is None:
                raise ValueError('kickoff_timezone_missing')
            if not pd.Timedelta(minutes=5) <= kickoff - now <= pd.Timedelta(hours=24):
                raise ValueError('outside_5min_24h_window')
            # Football-Data's fixture clock is UK local time. Require agreement,
            # instead of replacing the previous independent schedule check silently.
            provider_time = pd.Timestamp(f"{day} {row['Time']}").tz_localize('Europe/London')
            if abs(provider_time - kickoff) > pd.Timedelta(minutes=1):
                raise ValueError('independent_schedule_disagreement')
            quotes = {key: float(row['B365' + suffix]) for key, suffix in
                      [('home', 'H'), ('draw', 'D'), ('away', 'A')]}
            price_frame(quotes)  # Validate before the model sees any input.
            candidates.append(dict(fixture_id=cat['fixture_id'], production_fixture_id=cat['fixture_id'],
                                   league='EPL', home_team=cat['home_team'], away_team=cat['away_team'],
                                   kickoff_utc=kickoff.isoformat(), schedule_source=cat['schedule_source'],
                                   quotes={'B365': quotes}))
        except (KeyError, ValueError, TypeError) as error:
            rejected.append(dict(**tag, reason=str(error)))
    if len({c['fixture_id'] for c in candidates}) != len(candidates):
        raise ValueError('Duplicate eligible price-only fixture')
    return candidates, rejected
