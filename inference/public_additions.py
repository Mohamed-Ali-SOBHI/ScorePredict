"""Frozen candidates promoted prospectively; observation journals remain unchanged."""
from datetime import datetime
import math
from pathlib import Path
import os
import subprocess
import sys

ACTIVATED_AT = '2026-10-25T19:23:42+00:00'
BUNDESLIGA = 'public_bundesliga_xgb_2026_10_25'
ENGLAND_HOME = 'public_epl_home_price_2026_10_25'
STRATEGIES = {
    BUNDESLIGA: dict(league='Bundesliga', outcome='draw', model='native_mean', threshold=.02,
                    label='Bundesliga · nul XGBoost'),
    ENGLAND_HOME: dict(league='EPL', outcome='home_win', model='local_price_only', threshold=.02,
                      label='Premier League · victoire à domicile'),
}


def qualifies(probability, odds):
    try:
        p, price = float(probability), float(odds)
        return math.isfinite(p) and math.isfinite(price) and 0 <= p <= 1 and 1.2 <= price <= 10 and p * price * .98 - 1 > .02
    except (TypeError, ValueError):
        return False


def public_addition_row(row, strategy):
    spec = STRATEGIES[strategy]
    if str(row.get('portfolio_name', '')).startswith(('private_', 'observation_')):
        return False
    if row.get('league') != spec['league'] or row.get('outcome', row.get('selected_outcome')) != spec['outcome']:
        return False
    try:
        stamp = datetime.fromisoformat(row.get('recordedAt', row.get('prediction_generated_at_utc', '')).replace('Z', '+00:00'))
        if stamp < datetime.fromisoformat(ACTIVATED_AT):
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    return qualifies(row.get('modelProbability', row.get('predicted_probability')), row.get('odds', row.get('selected_odds')))


def score_public_additions(catalog, future_df, output_dir):
    import pandas as pd
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / 'scored.csv'
    output.unlink(missing_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
    subprocess.run([sys.executable, str(Path(__file__).with_name('public_additions_worker.py')),
                    '--catalog', str(Path(catalog).resolve()), '--output', str(output)],
                   check=True, timeout=600, env=env)
    scored = pd.read_csv(output)
    if scored.empty:
        return scored
    scored['recommended_bet'] = scored.recommended_bet.fillna('')
    rows = []
    for source in scored.to_dict('records'):
        candidates = future_df[future_df.fixture_id.astype(str).eq(source['fixture_id'])]
        if len(candidates) != 1:
            raise ValueError('New public strategy has no unique production fixture')
        row = candidates.iloc[0].to_dict()
        row.update(source)
        row['date'] = pd.Timestamp(source['kickoff_utc']).tz_convert('Europe/Paris').tz_localize(None)
        row['bet_key'] = str(row['match_id']) + '|' + row['selected_outcome']
        rows.append(row)
    return pd.DataFrame(rows)


def select_public_bets(scored, existing=None, portfolio=None):
    """Current rules first, then additions. A published fixture cannot switch sides."""
    import pandas as pd
    from data_pipeline.market_data import normalize_team_name
    from inference.kickoff_time import paris_date_key
    if scored.empty or 'recommended_bet' not in scored:
        return scored.iloc[0:0].copy()
    candidates = scored[scored.recommended_bet.fillna('').ne('')].copy()
    if candidates.empty:
        return candidates
    if candidates.fixture_id.isna().any() or candidates.fixture_id.astype(str).str.strip().eq('').any():
        raise ValueError('A public bet needs a verified fixture ID')
    candidates['_priority'] = candidates.strategy_name.map({BUNDESLIGA:1, ENGLAND_HOME:2}).fillna(0)
    candidates = candidates.sort_values('_priority', kind='stable').drop_duplicates('fixture_id', keep='first')
    candidates['strategy_names'] = candidates.strategy_name
    if existing is not None and not existing.empty:
        held = existing.copy()
        if portfolio is not None:
            held = held[held.portfolio_name.eq(portfolio)]
        if 'recommended' in held:
            held = held[held.recommended.astype(str).str.lower().isin(['true', '1', '1.0'])]
        def key(row):
            return (row.get('league'), paris_date_key(row.get('date')),
                    normalize_team_name(str(row.get('team_name', ''))), normalize_team_name(str(row.get('opponent_name', ''))))
        byid = {}; bykey = {}
        for row in held.to_dict('records'):
            identity = str(row.get('fixture_id', ''))
            if identity not in {'', 'nan', 'None'}:
                byid.setdefault(identity, []).append(row)
            bykey.setdefault(key(row), []).append(row)
        keep = []
        for row in candidates.to_dict('records'):
            previous = byid.get(str(row['fixture_id']), []) or bykey.get(key(row), [])
            keep.append(not previous or all(p['selected_outcome'] == row['selected_outcome']
                                            and p.get('strategy_names') == row['strategy_names'] for p in previous))
        candidates = candidates.loc[keep]
    return candidates.drop(columns='_priority').reset_index(drop=True)
