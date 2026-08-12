from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


OUTCOME_INDEX = {"away_win": 0, "draw": 1, "home_win": 2}
OUTCOME_LABELS = np.array(["away_win", "draw", "home_win"], dtype=object)
MARKET_PROB_COLS_MODEL_ORDER = [
    "market_away_prob_open",
    "market_draw_prob_open",
    "market_home_prob_open",
]


@dataclass(frozen=True)
class StrategyFamily:
    model_variant: str
    train_league: str
    bet_league: str
    outcome: str
    odds_min: float
    odds_max: float
    market_favorite_mode: str
    profile_filter: str = "any"

    @property
    def name(self) -> str:
        train_label = self.train_league or "ALL"
        bet_label = self.bet_league or "ALL"
        base = (
            f"model={self.model_variant}|train={train_label}|bet={bet_label}|outcome={self.outcome}|"
            f"odds=[{self.odds_min:.2f},{self.odds_max:.2f})|fav={self.market_favorite_mode}"
        )
        if self.profile_filter == "any":
            return base
        return f"{base}|profile={self.profile_filter}"


def sample_params(rng: np.random.Generator) -> dict:
    return {
        "max_depth": int(rng.integers(3, 9)),
        "min_child_weight": float(rng.uniform(1.0, 12.0)),
        "subsample": float(rng.uniform(0.55, 1.0)),
        "colsample_bytree": float(rng.uniform(0.55, 1.0)),
        "gamma": float(rng.uniform(0.0, 4.0)),
        "reg_lambda": float(rng.uniform(0.5, 8.0)),
        "learning_rate": float(rng.uniform(0.015, 0.08)),
    }


def build_base_bets(eval_df: pd.DataFrame, proba: np.ndarray) -> pd.DataFrame:
    odds = np.column_stack(
        [
            eval_df["market_away_win_odds_open"].to_numpy(),
            eval_df["market_draw_odds_open"].to_numpy(),
            eval_df["market_home_win_odds_open"].to_numpy(),
        ]
    )
    fair_probs = 1.0 / odds
    fair_probs = fair_probs / fair_probs.sum(axis=1, keepdims=True)
    expected_value = proba * odds - 1.0
    chosen = expected_value.argmax(axis=1)
    chosen_ev = expected_value[np.arange(len(expected_value)), chosen]

    bet_df = eval_df.copy()
    bet_df["selected_outcome"] = OUTCOME_LABELS[chosen]
    bet_df["selected_odds"] = odds[np.arange(len(odds)), chosen]
    bet_df["predicted_probability"] = proba[np.arange(len(proba)), chosen]
    bet_df["market_probability"] = fair_probs[np.arange(len(fair_probs)), chosen]
    bet_df["edge"] = bet_df["predicted_probability"] - bet_df["market_probability"]
    bet_df["expected_value"] = chosen_ev
    bet_df["raw_model_probability"] = bet_df["predicted_probability"]
    bet_df["value_score"] = bet_df["edge"]
    bet_df["raw_expected_value"] = bet_df["expected_value"]
    bet_df["probability_note"] = "raw_xgb_probability_not_calibrated"
    bet_df["won_bet"] = chosen == bet_df["target"].astype(int).to_numpy()
    bet_df["profit"] = np.where(bet_df["won_bet"], bet_df["selected_odds"] - 1.0, -1.0)

    valid_mask = np.isfinite(odds).all(axis=1) & (odds > 1.0).all(axis=1)
    bet_df = bet_df[valid_mask].copy()

    market_probs = bet_df[MARKET_PROB_COLS_MODEL_ORDER].to_numpy()
    market_fav_idx = market_probs.argmax(axis=1)
    selected_idx = pd.Series(bet_df["selected_outcome"]).map(OUTCOME_INDEX).to_numpy()
    bet_df["bet_is_market_favorite"] = selected_idx == market_fav_idx
    bet_df["bet_key"] = bet_df["match_id"].astype(str) + "|" + bet_df["selected_outcome"].astype(str)
    return bet_df


def build_draw_binary_bets(eval_df: pd.DataFrame, draw_proba: np.ndarray) -> pd.DataFrame:
    bet_df = eval_df.copy()
    selected_odds = eval_df["market_draw_odds_open"].to_numpy(dtype=float)
    predicted_probability = np.asarray(draw_proba, dtype=float)
    market_probability = eval_df["market_draw_prob_open"].to_numpy(dtype=float)

    bet_df["selected_outcome"] = "draw"
    bet_df["selected_odds"] = selected_odds
    bet_df["predicted_probability"] = predicted_probability
    bet_df["market_probability"] = market_probability
    bet_df["edge"] = bet_df["predicted_probability"] - bet_df["market_probability"]
    bet_df["expected_value"] = bet_df["predicted_probability"] * bet_df["selected_odds"] - 1.0
    bet_df["raw_model_probability"] = bet_df["predicted_probability"]
    bet_df["value_score"] = bet_df["edge"]
    bet_df["raw_expected_value"] = bet_df["expected_value"]
    bet_df["probability_note"] = "raw_xgb_probability_not_calibrated"
    bet_df["won_bet"] = bet_df["target"].astype(int).to_numpy() == OUTCOME_INDEX["draw"]
    bet_df["profit"] = np.where(bet_df["won_bet"], bet_df["selected_odds"] - 1.0, -1.0)

    valid_mask = np.isfinite(selected_odds) & (selected_odds > 1.0) & np.isfinite(predicted_probability)
    bet_df = bet_df[valid_mask].copy()

    market_probs = bet_df[MARKET_PROB_COLS_MODEL_ORDER].to_numpy()
    market_fav_idx = market_probs.argmax(axis=1)
    bet_df["bet_is_market_favorite"] = market_fav_idx == OUTCOME_INDEX["draw"]
    bet_df["bet_key"] = bet_df["match_id"].astype(str) + "|draw"
    return bet_df


KNOWN_PROFILE_FILTERS = {
    "any",
    "low_event_parity",
    "false_favorite_draw",
    "strict_consensus",
    "league_regime_draw",
    "favorite_fatigue_trap",
    "underdog_resistance",
    "anti_overconfidence",
}


def validate_profile_filter(profile_filter: str) -> None:
    if profile_filter not in KNOWN_PROFILE_FILTERS:
        raise ValueError(
            f"Unknown profile filter {profile_filter!r}; expected one of {sorted(KNOWN_PROFILE_FILTERS)}"
        )


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def profile_filter_mask(base_bets: pd.DataFrame, profile_filter: str) -> pd.Series:
    validate_profile_filter(profile_filter)
    mask = pd.Series(True, index=base_bets.index)
    if profile_filter == "any":
        return mask

    selected_odds = _series(base_bets, "selected_odds")
    expected_value = _series(base_bets, "expected_value")
    edge = _series(base_bets, "edge")
    draw_abs_elo_gap = _series(base_bets, "draw_abs_elo_gap")
    draw_elo_parity = _series(base_bets, "draw_elo_parity")
    draw_abs_xg_gap = _series(base_bets, "draw_abs_xG_advantage_5_carry")
    draw_abs_def_gap = _series(base_bets, "draw_abs_defensive_advantage_5_carry")
    draw_abs_form_gap = _series(base_bets, "draw_abs_relative_form_5_carry")
    total_xg_for = _series(base_bets, "draw_total_xG_last_5_carry")
    total_xg_against = _series(base_bets, "draw_total_xG_against_last_5_carry")
    market_home_away_gap = _series(base_bets, "draw_market_home_away_gap_open").abs()
    market_triplet_std = _series(base_bets, "draw_market_triplet_std_open")
    market_favorite_gap = _series(base_bets, "market_favorite_gap_open")
    market_favorite_prob = _series(base_bets, "market_favorite_prob_open")
    market_home_prob = _series(base_bets, "market_home_prob_open")
    market_away_prob = _series(base_bets, "market_away_prob_open")
    market_draw_prob = _series(base_bets, "market_draw_prob_open")
    rest_days_diff = _series(base_bets, "rest_days_diff")
    draw_abs_rest_days_diff = _series(base_bets, "draw_abs_rest_days_diff")
    combined_draw_rate = _series(base_bets, "draw_combined_draw_rate_10_carry")
    draw_rate_gap = _series(base_bets, "draw_draw_rate_gap_10_carry").abs()
    prev_draw_rate = (
        _series(base_bets, "prev_season_draw_rate")
        + _series(base_bets, "opponent_prev_season_draw_rate")
    )

    if profile_filter == "low_event_parity":
        return (
            mask
            & (draw_abs_elo_gap <= 75.0)
            & (draw_abs_xg_gap <= 0.55)
            & (draw_abs_def_gap <= 0.55)
            & (draw_abs_form_gap <= 5.5)
            & (market_home_away_gap <= 0.32)
            & (total_xg_for <= 2.90)
            & (total_xg_against <= 3.05)
        )

    if profile_filter == "false_favorite_draw":
        return (
            mask
            & (market_favorite_prob >= 0.48)
            & (market_favorite_prob <= 0.72)
            & (market_favorite_gap >= 0.14)
            & (market_favorite_gap <= 0.52)
            & (draw_elo_parity >= 0.55)
            & (draw_abs_xg_gap <= 0.85)
            & (draw_abs_def_gap <= 0.85)
            & (selected_odds >= 3.00)
        )

    if profile_filter == "strict_consensus":
        multiclass = _series(base_bets, "multiclass_draw_probability")
        binary = _series(base_bets, "binary_draw_probability")
        disagreement = (multiclass - binary).abs()
        return (
            mask
            & (multiclass >= market_draw_prob + 0.02)
            & (binary >= market_draw_prob + 0.02)
            & (multiclass >= 0.18)
            & (binary >= 0.18)
            & (disagreement <= 0.10)
            & (expected_value <= 1.80)
        )

    if profile_filter == "league_regime_draw":
        return (
            mask
            & (prev_draw_rate >= 0.43)
            & (combined_draw_rate >= 0.38)
            & (draw_rate_gap <= 0.30)
            & (market_triplet_std <= 0.26)
            & (selected_odds >= 3.00)
        )

    if profile_filter == "favorite_fatigue_trap":
        home_favorite_tired = (market_home_prob > market_away_prob) & (rest_days_diff <= -1.0)
        away_favorite_tired = (market_away_prob > market_home_prob) & (rest_days_diff >= 1.0)
        return (
            mask
            & (market_favorite_prob >= 0.48)
            & (market_favorite_gap >= 0.12)
            & (draw_abs_rest_days_diff >= 1.0)
            & (home_favorite_tired | away_favorite_tired)
            & (draw_abs_elo_gap <= 170.0)
            & (selected_odds >= 3.00)
        )

    if profile_filter == "underdog_resistance":
        return (
            mask
            & (market_favorite_prob >= 0.48)
            & (market_favorite_gap >= 0.12)
            & (draw_abs_def_gap <= 0.65)
            & (draw_abs_xg_gap <= 0.90)
            & (combined_draw_rate >= 0.30)
            & (selected_odds >= 3.00)
        )

    if profile_filter == "anti_overconfidence":
        return (
            mask
            & (edge >= 0.02)
            & (edge <= 0.24)
            & (expected_value <= 1.25)
            & (selected_odds <= 7.50)
        )

    raise AssertionError(f"Unhandled profile filter {profile_filter!r}")


def apply_strategy(
    base_bets: pd.DataFrame,
    *,
    threshold: float,
    edge_min: float,
    bet_league: str,
    outcome: str,
    odds_min: float,
    odds_max: float,
    market_favorite_mode: str,
    profile_filter: str = "any",
) -> pd.DataFrame:
    bets = base_bets[base_bets["expected_value"] > threshold].copy()
    if bet_league:
        bets = bets[bets["league"] == bet_league]
    bets = bets[bets["selected_outcome"] == outcome]
    bets = bets[(bets["selected_odds"] >= odds_min) & (bets["selected_odds"] < odds_max)]
    bets = bets[bets["edge"] >= edge_min]
    if market_favorite_mode == "favorite":
        bets = bets[bets["bet_is_market_favorite"]]
    elif market_favorite_mode == "nonfavorite":
        bets = bets[~bets["bet_is_market_favorite"]]
    bets = bets[profile_filter_mask(bets, profile_filter)]
    return bets


def threshold_values(start: float, stop: float, step: float) -> list[float]:
    values = np.arange(start, stop + step / 2.0, step)
    return [round(float(value), 10) for value in values]


def parse_list_argument(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def parse_odds_ranges(raw: str) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for token in parse_list_argument(raw):
        parts = token.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid odds range {token!r}; expected MIN:MAX")
        low = float(parts[0])
        high = float(parts[1])
        if high <= low:
            raise ValueError(f"Invalid odds range {token!r}; MAX must be > MIN")
        ranges.append((low, high))
    return ranges


def summarize_bets(bets: pd.DataFrame, prefix: str) -> dict[str, float | int | None]:
    if bets.empty:
        return {
            f"{prefix}_bets": 0,
            f"{prefix}_roi": None,
            f"{prefix}_profit": 0.0,
            f"{prefix}_hit_rate": None,
            f"{prefix}_avg_odds": None,
            f"{prefix}_avg_edge": None,
            f"{prefix}_avg_ev": None,
        }

    return {
        f"{prefix}_bets": int(len(bets)),
        f"{prefix}_roi": float(bets["profit"].mean()),
        f"{prefix}_profit": float(bets["profit"].sum()),
        f"{prefix}_hit_rate": float(bets["won_bet"].mean()),
        f"{prefix}_avg_odds": float(bets["selected_odds"].mean()),
        f"{prefix}_avg_edge": float(bets["edge"].mean()),
        f"{prefix}_avg_ev": float(bets["expected_value"].mean()),
    }
