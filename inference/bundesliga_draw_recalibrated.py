"""Prospective publication filter over the immutable September draw models.

Apply before deduplication and journaling. Never apply this filter to old tickets.
"""
import math

VERSION = 'bundesliga_draw_recalibrated_2026_10_25'
ACTIVATED_AT = '2026-10-25T11:10:28+00:00'
EV_THRESHOLD = .15
PRICE_HAIRCUT = .02
EDGE_MIN = .04


def qualifies(probability, odds, market_probability):
    try:
        p, price, q = float(probability), float(odds), float(market_probability)
    except (ValueError, TypeError):
        return False
    return (all(math.isfinite(x) for x in (p, price, q))
            and 0 <= p <= 1 and 0 <= q <= 1 and 2.2 <= price < 10
            and p * price * (1 - PRICE_HAIRCUT) - 1 > EV_THRESHOLD
            and p - q >= EDGE_MIN)


def apply_filter(scored):
    """Only tighten existing Bundesliga draw decisions; other gates remain intact."""
    result = scored.copy()
    if result.empty:
        return result
    mask = result['league'].eq('Bundesliga') & result['selected_outcome'].eq('draw')
    for idx, row in result.loc[mask].iterrows():
        if not qualifies(row.get('predicted_probability'), row.get('selected_odds'),
                         row.get('market_probability')):
            result.at[idx, 'recommended_bet'] = ''
        # Persist the filter version in the existing immutable ledger schema.
        original = str(row['strategy_name']).split('__filter_')[0]
        result.at[idx, 'strategy_name'] = original + '__filter_' + VERSION
    return result
