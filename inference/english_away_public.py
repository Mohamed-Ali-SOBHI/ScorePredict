"""Public English sleeve. Frozen sporting logit, B365 prices, fixed 1u stakes.

The scoring worker runs separately so its sealed feature modules cannot replace
the existing Bundesliga production modules in this process.
"""
from pathlib import Path
import os
import subprocess
import sys

STRATEGY = 'epl_away_logit_strict_2026_10_18'
ACTIVATED_AT = '2026-10-18T15:10:26+00:00'


def qualifies(probability, odds):
    import math
    try:
        p, price = float(probability), float(odds)
        return math.isfinite(p) and 0 <= p <= 1 and 2 <= price <= 6 and p * price * .98 - 1 > .10
    except (ValueError, TypeError):
        return False


def score_public_english(catalog, fixtures, future_df, output_dir):
    import pandas as pd
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / 'scored.csv'
    # Fresh file required; never reuse a prior successful capture after a failure.
    output.unlink(missing_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
    subprocess.run([sys.executable, str(Path(__file__).with_name('english_away_worker.py')),
                    '--catalog', str(Path(catalog).resolve()), '--output', str(output)],
                   check=True, timeout=300, env=env)
    english = pd.read_csv(output)
    if english.empty:
        return english
    english['recommended_bet'] = english['recommended_bet'].fillna('')
    # Use the same canonical fixture IDs and ledger match IDs as production.
    mapping = dict(zip(fixtures.fixture_id.astype(str), fixtures.index))
    rows = []
    for source in english.to_dict('records'):
        identity = source['fixture_id']
        if identity not in mapping:
            raise ValueError('English fixture missing from current production window')
        candidates = future_df[future_df.fixture_id.astype(str).eq(identity)]
        if len(candidates) != 1:
            raise ValueError('Ambiguous English production identity')
        row = candidates.iloc[0].to_dict()
        row.update(source)
        # Worker dates are UTC; ledger exports use the verified Paris kickoff.
        row['date'] = pd.Timestamp(source['kickoff_utc']).tz_convert('Europe/Paris').tz_localize(None)
        row['bet_key'] = str(row['match_id']) + '|away_win'
        rows.append(row)
    return pd.DataFrame(rows)


def fixed_unit_stakes(bets, unit_eur):
    """A constant stake per unique ticket, with no resizing on busy days."""
    result = bets.copy()
    if unit_eur <= 0:
        raise ValueError('A positive fixed unit is required')
    result['stake_eur'] = float(unit_eur)
    result['max_total_exposure_eur'] = len(result) * float(unit_eur)
    result['potential_profit_eur_if_win'] = ((result['selected_odds'] - 1) * float(unit_eur)
                                           if not result.empty else 0.0)
    return result
