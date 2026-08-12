import argparse
import glob
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from data_pipeline.market_data import enrich_team_rows_with_market_data


TEAM_MATCH_COLS = [
    "match_id",
    "date",
    "is_home",
    "team_id",
    "team_name",
    "result",
    "opponent_id",
    "opponent_name",
    # post-match stats (allowed ONLY via lag/rolling)
    "team_xG",
    "opponent_xG",
    "team_deep",
    "opponent_deep",
    "team_ppda_att",
    "team_ppda_def",
    "team_win_odds_open",
    "draw_odds_open",
    "opponent_win_odds_open",
]
OPTIONAL_TEAM_MATCH_COLS = [
    "team_win_odds_close",
    "draw_odds_close",
    "opponent_win_odds_close",
    "team_win_consensus_odds_open",
    "draw_consensus_odds_open",
    "opponent_win_consensus_odds_open",
    "team_win_consensus_odds_close",
    "draw_consensus_odds_close",
    "opponent_win_consensus_odds_close",
]

WINDOWS_DEFAULT = (1, 3, 5)
DEFAULT_DATA_DIR = REPO_ROOT / "Data"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "dataset_home.csv"


def load_team_match_rows(data_dir: str) -> pd.DataFrame:
    paths = glob.glob(f"{data_dir}/**/*.csv", recursive=True)
    if not paths:
        raise FileNotFoundError(f"No CSV files found under {data_dir!r}")

    dfs = []
    for path in paths:
        header = pd.read_csv(path, nrows=0).columns
        available_optional = [column for column in OPTIONAL_TEAM_MATCH_COLS if column in header]
        usecols = TEAM_MATCH_COLS + available_optional
        dfs.append(pd.read_csv(path, usecols=usecols))

    raw = pd.concat(dfs, ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"])

    for c in [
        "team_xG",
        "opponent_xG",
        "team_deep",
        "opponent_deep",
        "team_ppda_att",
        "team_ppda_def",
        "team_win_odds_open",
        "draw_odds_open",
        "opponent_win_odds_open",
        *OPTIONAL_TEAM_MATCH_COLS,
    ]:
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")

    raw["season_key"] = raw["match_id"].str.rsplit("_", n=3).str[0]
    raw["league"] = raw["season_key"].str.rsplit(" ", n=1).str[0]
    raw["season"] = raw["season_key"].str.rsplit(" ", n=1).str[1].astype(int)

    raw["team_id"] = raw["team_id"].astype(str)
    raw["opponent_id"] = raw["opponent_id"].astype(str)

    return raw


def _rolling_mean_prematch(series: pd.Series, window: int) -> pd.Series:
    if window == 1:
        return series.shift(1)
    return series.shift(1).rolling(window, min_periods=1).mean()


def _blend_mean_with_prior(
    current_mean: pd.Series,
    prior_mean: pd.Series,
    matches_before: pd.Series,
    window: int,
) -> pd.Series:
    current_count = np.minimum(matches_before.fillna(0.0).astype(float), float(window))
    prior_count = float(window) - current_count

    blended = current_mean.copy()
    has_prior = prior_mean.notna()
    blended.loc[has_prior] = (
        current_mean.loc[has_prior].fillna(0.0) * current_count.loc[has_prior]
        + prior_mean.loc[has_prior] * prior_count.loc[has_prior]
    ) / float(window)
    return blended


def _blend_sum_with_prior(
    current_sum: pd.Series,
    prior_points_per_game: pd.Series,
    matches_before: pd.Series,
    window: int,
) -> pd.Series:
    current_count = np.minimum(matches_before.fillna(0.0).astype(float), float(window))
    prior_count = float(window) - current_count

    blended = current_sum.copy()
    has_prior = prior_points_per_game.notna()
    blended.loc[has_prior] = (
        current_sum.loc[has_prior].fillna(0.0)
        + prior_points_per_game.loc[has_prior] * prior_count.loc[has_prior]
    )
    return blended


def add_team_prematch_features(team_rows: pd.DataFrame, windows: tuple[int, ...]) -> pd.DataFrame:
    """Adds prematch features with previous-season carry-over."""

    team_rows = team_rows.sort_values(["league", "season", "team_id", "date"]).copy()
    team_rows["_points"] = team_rows["result"].map({"w": 3, "d": 1, "l": 0}).astype(float)

    def _per_team_season(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()
        matches_before = pd.Series(np.arange(len(group)), index=group.index).astype(float)
        group["matches_played_in_season_before"] = matches_before
        draw_indicator = (group["result"] == "d").astype(float)

        for w in windows:
            group[f"team_xG_last_{w}"] = _rolling_mean_prematch(group["team_xG"], w)
            group[f"team_deep_last_{w}"] = _rolling_mean_prematch(group["team_deep"], w)
            group[f"team_xG_against_last_{w}"] = _rolling_mean_prematch(group["opponent_xG"], w)
            group[f"team_deep_against_last_{w}"] = _rolling_mean_prematch(group["opponent_deep"], w)
            group[f"team_ppda_att_last_{w}"] = _rolling_mean_prematch(group["team_ppda_att"], w)
            group[f"team_ppda_def_last_{w}"] = _rolling_mean_prematch(group["team_ppda_def"], w)

        group["form_score_5"] = group["_points"].shift(1).rolling(5, min_periods=1).sum()
        group["form_score_10"] = group["_points"].shift(1).rolling(10, min_periods=1).sum()
        group["team_draw_rate_5"] = draw_indicator.shift(1).rolling(5, min_periods=1).mean()
        group["team_draw_rate_10"] = draw_indicator.shift(1).rolling(10, min_periods=1).mean()
        group["form_momentum"] = (group["form_score_5"] / 5.0) - (group["form_score_10"] / 10.0)

        group["xG_efficiency_5"] = (
            group["_points"].shift(1).rolling(5, min_periods=1).sum()
            / (group["team_xG"].shift(1).rolling(5, min_periods=1).sum() + 1e-9)
        )
        group["recent_xG_trend"] = (
            group["team_xG"].shift(1).rolling(3, min_periods=1).mean()
            - group["team_xG"].shift(1).rolling(8, min_periods=1).mean()
        )
        group["defensive_trend"] = (
            group["opponent_xG"].shift(1).rolling(3, min_periods=1).mean()
            - group["opponent_xG"].shift(1).rolling(8, min_periods=1).mean()
        )

        group["team_rest_days"] = (group["date"] - group["date"].shift(1)).dt.total_seconds() / 86400.0

        denom = matches_before.replace(0.0, np.nan)
        group["team_season_points_per_game"] = group["_points"].shift(1).cumsum() / denom

        group["team_season_avg_xG"] = group["team_xG"].shift(1).expanding(min_periods=1).mean()
        group["team_season_avg_xG_against"] = group["opponent_xG"].shift(1).expanding(min_periods=1).mean()
        group["team_season_avg_deep"] = group["team_deep"].shift(1).expanding(min_periods=1).mean()
        group["team_season_avg_deep_against"] = group["opponent_deep"].shift(1).expanding(min_periods=1).mean()
        group["team_season_avg_ppda_att"] = group["team_ppda_att"].shift(1).expanding(min_periods=1).mean()
        group["team_season_avg_ppda_def"] = group["team_ppda_def"].shift(1).expanding(min_periods=1).mean()

        current_streak = []
        unbeaten_streak = []
        winless_streak = []

        win_streak = 0
        loss_streak = 0
        unbeaten = 0
        winless = 0

        for res in group["result"].tolist():
            if win_streak > 0:
                current_streak.append(win_streak)
            elif loss_streak > 0:
                current_streak.append(-loss_streak)
            else:
                current_streak.append(0)

            unbeaten_streak.append(unbeaten)
            winless_streak.append(winless)

            if res == "w":
                win_streak += 1
                loss_streak = 0
            elif res == "l":
                loss_streak += 1
                win_streak = 0
            else:
                win_streak = 0
                loss_streak = 0

            if res in ("w", "d"):
                unbeaten += 1
            else:
                unbeaten = 0

            if res in ("d", "l"):
                winless += 1
            else:
                winless = 0

        group["current_streak"] = current_streak
        group["unbeaten_streak"] = unbeaten_streak
        group["winless_streak"] = winless_streak

        return group

    team_rows = pd.concat(
        [
            _per_team_season(group)
            for _, group in team_rows.groupby(["league", "season", "team_id"], sort=False)
        ],
        axis=0,
    ).sort_index()

    season_summary = (
        team_rows.groupby(["league", "team_id", "season"], as_index=False)
        .agg(
            prev_season_points_per_game=("_points", "mean"),
            prev_season_avg_xG=("team_xG", "mean"),
            prev_season_avg_xG_against=("opponent_xG", "mean"),
            prev_season_avg_deep=("team_deep", "mean"),
            prev_season_avg_deep_against=("opponent_deep", "mean"),
            prev_season_avg_ppda_att=("team_ppda_att", "mean"),
            prev_season_avg_ppda_def=("team_ppda_def", "mean"),
            prev_season_draw_rate=("result", lambda values: (values == "d").mean()),
            prev_season_match_count=("match_id", "size"),
        )
        .copy()
    )
    season_summary["season"] = season_summary["season"] + 1

    team_rows = team_rows.merge(
        season_summary,
        on=["league", "team_id", "season"],
        how="left",
        validate="many_to_one",
    )

    matches_before = team_rows["matches_played_in_season_before"]
    for w in windows:
        team_rows[f"team_xG_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_xG_last_{w}"],
            team_rows["prev_season_avg_xG"],
            matches_before,
            w,
        )
        team_rows[f"team_deep_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_deep_last_{w}"],
            team_rows["prev_season_avg_deep"],
            matches_before,
            w,
        )
        team_rows[f"team_xG_against_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_xG_against_last_{w}"],
            team_rows["prev_season_avg_xG_against"],
            matches_before,
            w,
        )
        team_rows[f"team_deep_against_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_deep_against_last_{w}"],
            team_rows["prev_season_avg_deep_against"],
            matches_before,
            w,
        )
        team_rows[f"team_ppda_att_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_ppda_att_last_{w}"],
            team_rows["prev_season_avg_ppda_att"],
            matches_before,
            w,
        )
        team_rows[f"team_ppda_def_last_{w}_carry"] = _blend_mean_with_prior(
            team_rows[f"team_ppda_def_last_{w}"],
            team_rows["prev_season_avg_ppda_def"],
            matches_before,
            w,
        )

    team_rows["form_score_5_carry"] = _blend_sum_with_prior(
        team_rows["form_score_5"],
        team_rows["prev_season_points_per_game"],
        matches_before,
        5,
    )
    team_rows["form_score_10_carry"] = _blend_sum_with_prior(
        team_rows["form_score_10"],
        team_rows["prev_season_points_per_game"],
        matches_before,
        10,
    )
    team_rows["team_draw_rate_5_carry"] = _blend_mean_with_prior(
        team_rows["team_draw_rate_5"],
        team_rows["prev_season_draw_rate"],
        matches_before,
        5,
    )
    team_rows["team_draw_rate_10_carry"] = _blend_mean_with_prior(
        team_rows["team_draw_rate_10"],
        team_rows["prev_season_draw_rate"],
        matches_before,
        10,
    )

    team_rows["team_season_points_per_game_carry"] = team_rows["team_season_points_per_game"].fillna(
        team_rows["prev_season_points_per_game"]
    )
    team_rows["team_season_avg_xG_carry"] = team_rows["team_season_avg_xG"].fillna(team_rows["prev_season_avg_xG"])
    team_rows["team_season_avg_xG_against_carry"] = team_rows["team_season_avg_xG_against"].fillna(
        team_rows["prev_season_avg_xG_against"]
    )
    team_rows["team_season_avg_deep_carry"] = team_rows["team_season_avg_deep"].fillna(
        team_rows["prev_season_avg_deep"]
    )
    team_rows["team_season_avg_deep_against_carry"] = team_rows["team_season_avg_deep_against"].fillna(
        team_rows["prev_season_avg_deep_against"]
    )
    team_rows["team_season_avg_ppda_att_carry"] = team_rows["team_season_avg_ppda_att"].fillna(
        team_rows["prev_season_avg_ppda_att"]
    )
    team_rows["team_season_avg_ppda_def_carry"] = team_rows["team_season_avg_ppda_def"].fillna(
        team_rows["prev_season_avg_ppda_def"]
    )

    return team_rows


@dataclass
class EloConfig:
    initial: float = 1500.0
    k: float = 20.0
    home_adv: float = 60.0
    season_carry: float = 0.75


def compute_match_elo(matches: pd.DataFrame, config: EloConfig) -> pd.DataFrame:
    """Computes prematch Elo per league with cross-season carry-over."""

    matches = matches.sort_values(["league", "date", "match_id"]).copy()

    team_elo_home = []
    team_elo_away = []
    p_home = []

    for _, group in matches.groupby(["league"], sort=False):
        ratings: dict[str, float] = {}
        current_season: int | None = None

        for row in group.itertuples(index=False):
            if current_season is None:
                current_season = int(row.season)
            elif int(row.season) != current_season:
                ratings = {
                    team_id: config.initial + (rating - config.initial) * config.season_carry
                    for team_id, rating in ratings.items()
                }
                current_season = int(row.season)

            h = str(row.home_team_id)
            a = str(row.away_team_id)

            h_elo = ratings.get(h, config.initial)
            a_elo = ratings.get(a, config.initial)

            team_elo_home.append(h_elo)
            team_elo_away.append(a_elo)

            exp_home = 1.0 / (1.0 + 10 ** ((a_elo - (h_elo + config.home_adv)) / 400.0))
            p_home.append(exp_home)

            if pd.isna(row.result):
                continue

            if row.result == "w":
                score_home = 1.0
            elif row.result == "d":
                score_home = 0.5
            else:
                score_home = 0.0

            ratings[h] = h_elo + config.k * (score_home - exp_home)
            ratings[a] = a_elo + config.k * ((1.0 - score_home) - (1.0 - exp_home))

    matches["team_elo_rating"] = team_elo_home
    matches["opponent_elo_rating"] = team_elo_away
    matches["elo_win_probability"] = p_home
    matches["elo_rating_gap"] = matches["team_elo_rating"] - matches["opponent_elo_rating"]

    return matches[
        [
            "match_id",
            "team_elo_rating",
            "opponent_elo_rating",
            "elo_rating_gap",
            "elo_win_probability",
        ]
    ]


def add_market_implied_features(matches: pd.DataFrame) -> pd.DataFrame:
    matches = matches.copy()

    def add_probability_set(
        *,
        odds_suffix: str,
        feature_suffix: str,
        consensus: bool = False,
    ) -> None:
        odds_middle = "_consensus_odds_" if consensus else "_odds_"
        home_col = f"market_home_win{odds_middle}{odds_suffix}"
        draw_col = f"market_draw{odds_middle}{odds_suffix}"
        away_col = f"market_away_win{odds_middle}{odds_suffix}"
        if not {home_col, draw_col, away_col}.issubset(matches.columns):
            return

        inv_home = 1.0 / pd.to_numeric(matches[home_col], errors="coerce")
        inv_draw = 1.0 / pd.to_numeric(matches[draw_col], errors="coerce")
        inv_away = 1.0 / pd.to_numeric(matches[away_col], errors="coerce")

        overround = inv_home + inv_draw + inv_away
        matches[f"market_overround_{feature_suffix}"] = overround
        matches[f"market_home_prob_{feature_suffix}"] = inv_home / overround
        matches[f"market_draw_prob_{feature_suffix}"] = inv_draw / overround
        matches[f"market_away_prob_{feature_suffix}"] = inv_away / overround
        matches[f"market_home_minus_away_prob_{feature_suffix}"] = (
            matches[f"market_home_prob_{feature_suffix}"] - matches[f"market_away_prob_{feature_suffix}"]
        )
        matches[f"market_non_draw_prob_{feature_suffix}"] = 1.0 - matches[f"market_draw_prob_{feature_suffix}"]

        probs = matches[
            [
                f"market_home_prob_{feature_suffix}",
                f"market_draw_prob_{feature_suffix}",
                f"market_away_prob_{feature_suffix}",
            ]
        ]
        missing_market = probs.isna().any(axis=1)
        matches[f"market_favorite_prob_{feature_suffix}"] = probs.max(axis=1)

        probs_array = np.nan_to_num(probs.to_numpy(), nan=-1.0)
        second_highest = np.sort(probs_array, axis=1)[:, -2]
        second_highest[missing_market.to_numpy()] = np.nan
        matches[f"market_favorite_gap_{feature_suffix}"] = (
            matches[f"market_favorite_prob_{feature_suffix}"] - second_highest
        )

        entropy_input = probs.clip(lower=1e-12)
        matches[f"market_entropy_{feature_suffix}"] = -(entropy_input * np.log(entropy_input)).sum(axis=1)
        matches.loc[missing_market, f"market_entropy_{feature_suffix}"] = np.nan

    add_probability_set(odds_suffix="open", feature_suffix="open")
    add_probability_set(odds_suffix="close", feature_suffix="close")
    add_probability_set(odds_suffix="open", feature_suffix="consensus_open", consensus=True)
    add_probability_set(odds_suffix="close", feature_suffix="consensus_close", consensus=True)

    if {
        "market_home_win_odds_close",
        "market_draw_odds_close",
        "market_away_win_odds_close",
    }.issubset(matches.columns):
        for outcome in ["home_win", "draw", "away_win"]:
            matches[f"market_{outcome}_odds_move_close_minus_open"] = (
                matches[f"market_{outcome}_odds_close"] - matches[f"market_{outcome}_odds_open"]
            )
            matches[f"market_{outcome}_prob_move_close_minus_open"] = (
                matches[f"market_{outcome.replace('_win', '') if outcome != 'draw' else outcome}_prob_close"]
                - matches[f"market_{outcome.replace('_win', '') if outcome != 'draw' else outcome}_prob_open"]
            )
        matches["market_entropy_move_close_minus_open"] = (
            matches["market_entropy_close"] - matches["market_entropy_open"]
        )
        matches["market_favorite_prob_move_close_minus_open"] = (
            matches["market_favorite_prob_close"] - matches["market_favorite_prob_open"]
        )

    if {
        "market_home_win_consensus_odds_open",
        "market_draw_consensus_odds_open",
        "market_away_win_consensus_odds_open",
    }.issubset(matches.columns):
        for outcome in ["home_win", "draw", "away_win"]:
            matches[f"market_{outcome}_consensus_odds_diff_open"] = (
                matches[f"market_{outcome}_consensus_odds_open"] - matches[f"market_{outcome}_odds_open"]
            )
    if {
        "market_home_win_consensus_odds_close",
        "market_draw_consensus_odds_close",
        "market_away_win_consensus_odds_close",
        "market_home_win_odds_close",
        "market_draw_odds_close",
        "market_away_win_odds_close",
    }.issubset(matches.columns):
        for outcome in ["home_win", "draw", "away_win"]:
            matches[f"market_{outcome}_consensus_odds_diff_close"] = (
                matches[f"market_{outcome}_consensus_odds_close"] - matches[f"market_{outcome}_odds_close"]
            )
    return matches


def add_draw_specialist_features(matches: pd.DataFrame, windows: tuple[int, ...]) -> pd.DataFrame:
    matches = matches.copy()

    draw_features = {
        "draw_abs_rest_days_diff": matches["rest_days_diff"].abs(),
        "draw_abs_relative_form_5": matches["relative_form_5"].abs(),
        "draw_abs_relative_form_10": matches["relative_form_10"].abs(),
        "draw_abs_relative_form_5_carry": matches["relative_form_5_carry"].abs(),
        "draw_abs_relative_form_10_carry": matches["relative_form_10_carry"].abs(),
        "draw_abs_xG_efficiency_gap_5": matches["xG_efficiency_gap_5"].abs(),
        "draw_abs_xG_trend_gap": matches["xG_trend_gap"].abs(),
        "draw_abs_defensive_trend_gap": matches["defensive_trend_gap"].abs(),
        "draw_abs_prev_season_points_gap": matches["prev_season_points_per_game_gap"].abs(),
        "draw_abs_prev_season_xG_gap": matches["prev_season_xG_gap"].abs(),
        "draw_abs_prev_season_defensive_gap": matches["prev_season_defensive_gap"].abs(),
        "draw_abs_season_points_gap": matches["season_points_per_game_gap"].abs(),
        "draw_combined_draw_rate_5": (
            matches["team_draw_rate_5"] + matches["opponent_draw_rate_5"]
        ) / 2.0,
        "draw_combined_draw_rate_10": (
            matches["team_draw_rate_10"] + matches["opponent_draw_rate_10"]
        ) / 2.0,
        "draw_draw_rate_gap_5": (
            matches["team_draw_rate_5"] - matches["opponent_draw_rate_5"]
        ).abs(),
        "draw_draw_rate_gap_10": (
            matches["team_draw_rate_10"] - matches["opponent_draw_rate_10"]
        ).abs(),
        "draw_combined_draw_rate_5_carry": (
            matches["team_draw_rate_5_carry"] + matches["opponent_draw_rate_5_carry"]
        ) / 2.0,
        "draw_combined_draw_rate_10_carry": (
            matches["team_draw_rate_10_carry"] + matches["opponent_draw_rate_10_carry"]
        ) / 2.0,
        "draw_draw_rate_gap_5_carry": (
            matches["team_draw_rate_5_carry"] - matches["opponent_draw_rate_5_carry"]
        ).abs(),
        "draw_draw_rate_gap_10_carry": (
            matches["team_draw_rate_10_carry"] - matches["opponent_draw_rate_10_carry"]
        ).abs(),
        "draw_market_home_away_gap_open": (
            matches["market_home_prob_open"] - matches["market_away_prob_open"]
        ).abs(),
        "draw_market_draw_vs_home_gap_open": (
            matches["market_draw_prob_open"] - matches["market_home_prob_open"]
        ).abs(),
        "draw_market_draw_vs_away_gap_open": (
            matches["market_draw_prob_open"] - matches["market_away_prob_open"]
        ).abs(),
        "draw_market_draw_to_non_draw_ratio_open": (
            matches["market_draw_prob_open"] / matches["market_non_draw_prob_open"]
        ),
        "draw_market_triplet_std_open": matches[
            ["market_home_prob_open", "market_draw_prob_open", "market_away_prob_open"]
        ].std(axis=1),
    }
    draw_features["draw_market_balance_open"] = 1.0 - draw_features["draw_market_home_away_gap_open"]

    if "elo_rating_gap" in matches.columns:
        draw_features["draw_abs_elo_gap"] = matches["elo_rating_gap"].abs()
        draw_features["draw_elo_parity"] = 1.0 - ((matches["elo_win_probability"] - 0.5).abs() * 2.0)

    for w in windows:
        draw_features.update(
            {
                f"draw_abs_xG_advantage_{w}": matches[f"xG_advantage_{w}"].abs(),
                f"draw_abs_defensive_advantage_{w}": matches[f"defensive_advantage_{w}"].abs(),
                f"draw_abs_deep_advantage_{w}": matches[f"deep_advantage_{w}"].abs(),
                f"draw_abs_ppda_advantage_{w}": matches[f"ppda_advantage_{w}"].abs(),
                f"draw_abs_xG_advantage_{w}_carry": matches[f"xG_advantage_{w}_carry"].abs(),
                f"draw_abs_defensive_advantage_{w}_carry": matches[
                    f"defensive_advantage_{w}_carry"
                ].abs(),
                f"draw_abs_deep_advantage_{w}_carry": matches[f"deep_advantage_{w}_carry"].abs(),
                f"draw_abs_ppda_advantage_{w}_carry": matches[f"ppda_advantage_{w}_carry"].abs(),
                f"draw_total_xG_last_{w}": (
                    matches[f"team_xG_last_{w}"] + matches[f"opponent_xG_last_{w}"]
                ),
                f"draw_total_xG_against_last_{w}": (
                    matches[f"team_xG_against_last_{w}"] + matches[f"opponent_xG_against_last_{w}"]
                ),
                f"draw_total_deep_last_{w}": (
                    matches[f"team_deep_last_{w}"] + matches[f"opponent_deep_last_{w}"]
                ),
                f"draw_total_deep_against_last_{w}": (
                    matches[f"team_deep_against_last_{w}"] + matches[f"opponent_deep_against_last_{w}"]
                ),
                f"draw_total_xG_last_{w}_carry": (
                    matches[f"team_xG_last_{w}_carry"] + matches[f"opponent_xG_last_{w}_carry"]
                ),
                f"draw_total_xG_against_last_{w}_carry": (
                    matches[f"team_xG_against_last_{w}_carry"]
                    + matches[f"opponent_xG_against_last_{w}_carry"]
                ),
                f"draw_total_deep_last_{w}_carry": (
                    matches[f"team_deep_last_{w}_carry"] + matches[f"opponent_deep_last_{w}_carry"]
                ),
                f"draw_total_deep_against_last_{w}_carry": (
                    matches[f"team_deep_against_last_{w}_carry"]
                    + matches[f"opponent_deep_against_last_{w}_carry"]
                ),
            }
        )

    draw_nonfavorite = (
        matches["market_draw_prob_open"]
        < matches[["market_home_prob_open", "market_away_prob_open"]].max(axis=1)
    )
    odds_2_2_to_4_0 = matches["market_draw_odds_open"].between(2.2, 4.0, inclusive="left")
    odds_3_2_to_4_8 = matches["market_draw_odds_open"].between(3.2, 4.8, inclusive="left")
    odds_4_0_to_10_0 = matches["market_draw_odds_open"].between(4.0, 10.0, inclusive="left")
    odds_2_0_to_10_0 = matches["market_draw_odds_open"].between(2.0, 10.0, inclusive="left")

    draw_abs_elo_gap = draw_features.get(
        "draw_abs_elo_gap",
        pd.Series(np.nan, index=matches.index),
    )
    draw_abs_xg_gap = draw_features["draw_abs_xG_advantage_5_carry"]
    draw_abs_def_gap = draw_features["draw_abs_defensive_advantage_5_carry"]
    market_home_away_gap = draw_features["draw_market_home_away_gap_open"].abs()
    total_xg = draw_features["draw_total_xG_last_5_carry"]
    total_xga = draw_features["draw_total_xG_against_last_5_carry"]

    low_event_loose = (
        draw_nonfavorite
        & (draw_abs_elo_gap <= 170.0)
        & (draw_abs_xg_gap <= 0.85)
        & (draw_abs_def_gap <= 0.85)
        & (market_home_away_gap <= 0.55)
        & (total_xg <= 3.20)
        & (total_xga <= 3.05)
    )
    low_event_medium = (
        draw_nonfavorite
        & (draw_abs_elo_gap <= 170.0)
        & (draw_abs_xg_gap <= 0.55)
        & (draw_abs_def_gap <= 0.85)
        & (market_home_away_gap <= 0.55)
        & (total_xg <= 2.90)
        & (total_xga <= 3.05)
    )
    low_event_strict = (
        draw_nonfavorite
        & (draw_abs_elo_gap <= 120.0)
        & (draw_abs_xg_gap <= 0.55)
        & (draw_abs_def_gap <= 0.85)
        & (market_home_away_gap <= 0.55)
        & (total_xg <= 2.90)
        & (total_xga <= 3.05)
    )
    candidate_league = matches["league"].isin(["Bundesliga", "Ligue_1", "Serie_A"])
    low_event_candidate = low_event_medium & candidate_league & odds_2_0_to_10_0

    def _component_score(series: pd.Series, limit: float) -> pd.Series:
        return (1.0 - (series / limit)).clip(lower=0.0, upper=1.0)

    low_event_score = pd.concat(
        [
            _component_score(draw_abs_elo_gap, 170.0),
            _component_score(draw_abs_xg_gap, 0.85),
            _component_score(draw_abs_def_gap, 0.85),
            _component_score(market_home_away_gap, 0.55),
            _component_score(total_xg, 3.20),
            _component_score(total_xga, 3.05),
        ],
        axis=1,
    ).mean(axis=1)

    draw_features.update(
        {
            "algo_draw_nonfavorite": draw_nonfavorite.astype(float),
            "algo_draw_odds_2_2_to_4_0": odds_2_2_to_4_0.astype(float),
            "algo_draw_odds_3_2_to_4_8": odds_3_2_to_4_8.astype(float),
            "algo_draw_odds_4_0_to_10_0": odds_4_0_to_10_0.astype(float),
            "algo_draw_odds_2_0_to_10_0": odds_2_0_to_10_0.astype(float),
            "algo_low_event_parity_loose": low_event_loose.astype(float),
            "algo_low_event_parity_medium": low_event_medium.astype(float),
            "algo_low_event_parity_strict": low_event_strict.astype(float),
            "algo_low_event_parity_medium_mid_odds": (low_event_medium & odds_3_2_to_4_8).astype(float),
            "algo_low_event_parity_medium_long_odds": (low_event_medium & odds_4_0_to_10_0).astype(float),
            "algo_low_event_parity_strict_mid_odds": (low_event_strict & odds_3_2_to_4_8).astype(float),
            "algo_low_event_parity_strict_long_odds": (low_event_strict & odds_4_0_to_10_0).astype(float),
            "algo_low_event_parity_2026_candidate": low_event_candidate.astype(float),
            "algo_low_event_parity_score": low_event_score,
        }
    )

    return pd.concat([matches, pd.DataFrame(draw_features, index=matches.index)], axis=1).copy()


def build_home_perspective_dataset(team_rows: pd.DataFrame, windows: tuple[int, ...]) -> pd.DataFrame:
    home = team_rows[team_rows["is_home"] == True].copy()
    away = team_rows[team_rows["is_home"] == False].copy()

    team_feature_cols = []
    for w in windows:
        team_feature_cols += [
            f"team_xG_last_{w}",
            f"team_deep_last_{w}",
            f"team_xG_against_last_{w}",
            f"team_deep_against_last_{w}",
            f"team_ppda_att_last_{w}",
            f"team_ppda_def_last_{w}",
            f"team_xG_last_{w}_carry",
            f"team_deep_last_{w}_carry",
            f"team_xG_against_last_{w}_carry",
            f"team_deep_against_last_{w}_carry",
            f"team_ppda_att_last_{w}_carry",
            f"team_ppda_def_last_{w}_carry",
        ]

    team_feature_cols += [
        "matches_played_in_season_before",
        "form_score_5",
        "form_score_10",
        "team_draw_rate_5",
        "team_draw_rate_10",
        "form_score_5_carry",
        "form_score_10_carry",
        "team_draw_rate_5_carry",
        "team_draw_rate_10_carry",
        "form_momentum",
        "current_streak",
        "unbeaten_streak",
        "winless_streak",
        "prev_season_points_per_game",
        "prev_season_avg_xG",
        "prev_season_avg_xG_against",
        "prev_season_avg_deep",
        "prev_season_avg_deep_against",
        "prev_season_avg_ppda_att",
        "prev_season_avg_ppda_def",
        "prev_season_draw_rate",
        "prev_season_match_count",
        "team_season_points_per_game",
        "team_season_points_per_game_carry",
        "team_season_avg_xG",
        "team_season_avg_xG_against",
        "team_season_avg_deep",
        "team_season_avg_deep_against",
        "team_season_avg_ppda_att",
        "team_season_avg_ppda_def",
        "team_season_avg_xG_carry",
        "team_season_avg_xG_against_carry",
        "team_season_avg_deep_carry",
        "team_season_avg_deep_against_carry",
        "team_season_avg_ppda_att_carry",
        "team_season_avg_ppda_def_carry",
        "team_rest_days",
        "xG_efficiency_5",
        "recent_xG_trend",
        "defensive_trend",
    ]

    base_cols = [
        "match_id",
        "date",
        "league",
        "season",
        "team_id",
        "team_name",
        "opponent_id",
        "opponent_name",
        "result",
    ]
    market_cols = [
        "team_win_odds_open",
        "draw_odds_open",
        "opponent_win_odds_open",
    ]
    optional_market_cols = [column for column in OPTIONAL_TEAM_MATCH_COLS if column in home.columns]
    market_cols += optional_market_cols

    home_df = home[base_cols + team_feature_cols + market_cols].copy()
    market_rename_map = {
        "team_win_odds_open": "market_home_win_odds_open",
        "draw_odds_open": "market_draw_odds_open",
        "opponent_win_odds_open": "market_away_win_odds_open",
        "team_win_odds_close": "market_home_win_odds_close",
        "draw_odds_close": "market_draw_odds_close",
        "opponent_win_odds_close": "market_away_win_odds_close",
        "team_win_consensus_odds_open": "market_home_win_consensus_odds_open",
        "draw_consensus_odds_open": "market_draw_consensus_odds_open",
        "opponent_win_consensus_odds_open": "market_away_win_consensus_odds_open",
        "team_win_consensus_odds_close": "market_home_win_consensus_odds_close",
        "draw_consensus_odds_close": "market_draw_consensus_odds_close",
        "opponent_win_consensus_odds_close": "market_away_win_consensus_odds_close",
    }
    home_df = home_df.rename(columns=market_rename_map)

    away_df = away[["match_id", "team_id", "team_name", "opponent_id"] + team_feature_cols].copy()

    rename_map = {
        "team_id": "away_team_id",
        "team_name": "away_team_name",
        "opponent_id": "away_opponent_id",
    }
    for c in team_feature_cols:
        if c.startswith("team_"):
            rename_map[c] = "opponent_" + c[len("team_") :]
        else:
            rename_map[c] = "opponent_" + c

    away_df = away_df.rename(columns=rename_map)

    matches = home_df.merge(away_df, on="match_id", how="inner", validate="one_to_one")

    bad = matches[
        (matches["opponent_id"] != matches["away_team_id"])
        | (matches["away_opponent_id"] != matches["team_id"])
    ]
    if len(bad) > 0:
        raise ValueError(f"Join mismatch: {len(bad)} rows have inconsistent opponents")

    matches["rest_days_diff"] = matches["team_rest_days"] - matches["opponent_rest_days"]
    matches["rest_days_ratio"] = matches["team_rest_days"] / matches["opponent_rest_days"]

    matches["relative_form_5"] = matches["form_score_5"] - matches["opponent_form_score_5"]
    matches["relative_form_10"] = matches["form_score_10"] - matches["opponent_form_score_10"]
    matches["relative_form_5_carry"] = matches["form_score_5_carry"] - matches["opponent_form_score_5_carry"]
    matches["relative_form_10_carry"] = matches["form_score_10_carry"] - matches["opponent_form_score_10_carry"]

    matches["xG_efficiency_gap_5"] = matches["xG_efficiency_5"] - matches["opponent_xG_efficiency_5"]
    matches["xG_trend_gap"] = matches["recent_xG_trend"] - matches["opponent_recent_xG_trend"]
    matches["defensive_trend_gap"] = matches["defensive_trend"] - matches["opponent_defensive_trend"]

    matches["prev_season_points_per_game_gap"] = (
        matches["prev_season_points_per_game"] - matches["opponent_prev_season_points_per_game"]
    )
    matches["prev_season_xG_gap"] = matches["prev_season_avg_xG"] - matches["opponent_prev_season_avg_xG"]
    matches["prev_season_defensive_gap"] = (
        matches["opponent_prev_season_avg_xG_against"] - matches["prev_season_avg_xG_against"]
    )
    matches["season_points_per_game_gap"] = (
        matches["team_season_points_per_game_carry"] - matches["opponent_season_points_per_game_carry"]
    )

    for w in windows:
        matches[f"xG_advantage_{w}"] = matches[f"team_xG_last_{w}"] - matches[f"opponent_xG_last_{w}"]
        matches[f"defensive_advantage_{w}"] = (
            matches[f"opponent_xG_against_last_{w}"] - matches[f"team_xG_against_last_{w}"]
        )
        matches[f"deep_advantage_{w}"] = matches[f"team_deep_last_{w}"] - matches[f"opponent_deep_last_{w}"]
        matches[f"ppda_advantage_{w}"] = (
            matches[f"opponent_ppda_att_last_{w}"] - matches[f"team_ppda_att_last_{w}"]
        )

        matches[f"xG_advantage_{w}_carry"] = (
            matches[f"team_xG_last_{w}_carry"] - matches[f"opponent_xG_last_{w}_carry"]
        )
        matches[f"defensive_advantage_{w}_carry"] = (
            matches[f"opponent_xG_against_last_{w}_carry"] - matches[f"team_xG_against_last_{w}_carry"]
        )
        matches[f"deep_advantage_{w}_carry"] = (
            matches[f"team_deep_last_{w}_carry"] - matches[f"opponent_deep_last_{w}_carry"]
        )
        matches[f"ppda_advantage_{w}_carry"] = (
            matches[f"opponent_ppda_att_last_{w}_carry"] - matches[f"team_ppda_att_last_{w}_carry"]
        )

    matches = add_market_implied_features(matches)
    matches["target"] = matches["result"].map({"l": 0, "d": 1, "w": 2}).astype("Int64")
    matches = matches.drop(columns=["away_opponent_id"])

    return matches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--elo-k", type=float, default=20.0)
    parser.add_argument("--elo-home-adv", type=float, default=60.0)
    parser.add_argument("--elo-season-carry", type=float, default=0.75)
    parser.add_argument("--include-closing-market-data", action="store_true")
    parser.add_argument("--include-consensus-market-data", action="store_true")
    parser.add_argument(
        "--windows",
        default=",".join(str(w) for w in WINDOWS_DEFAULT),
        help="Comma-separated rolling windows (e.g. 1,3,5)",
    )
    args = parser.parse_args()

    windows = tuple(int(x) for x in args.windows.split(",") if x.strip())
    if not windows:
        raise ValueError("--windows must contain at least one integer")

    team_rows = load_team_match_rows(args.data_dir)
    if args.include_closing_market_data or args.include_consensus_market_data:
        team_rows, _ = enrich_team_rows_with_market_data(
            team_rows,
            include_closing=args.include_closing_market_data,
            include_consensus=args.include_consensus_market_data,
        )
    team_rows = add_team_prematch_features(team_rows, windows=windows)

    dataset = build_home_perspective_dataset(team_rows, windows=windows)

    elo_input = dataset[["match_id", "league", "season", "date", "team_id", "opponent_id", "result"]].rename(
        columns={"team_id": "home_team_id", "opponent_id": "away_team_id"}
    )
    elo = compute_match_elo(
        elo_input,
        EloConfig(
            k=args.elo_k,
            home_adv=args.elo_home_adv,
            season_carry=args.elo_season_carry,
        ),
    )
    dataset = dataset.merge(elo, on="match_id", how="left", validate="one_to_one")
    dataset = add_draw_specialist_features(dataset, windows=windows)

    market_odds_cols = [
        "market_home_win_odds_open",
        "market_draw_odds_open",
        "market_away_win_odds_open",
    ]
    missing_market_odds = dataset[market_odds_cols].isna().any(axis=1)
    dropped_missing_market_odds = int(missing_market_odds.sum())
    if dropped_missing_market_odds:
        dataset = dataset[~missing_market_odds].copy()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_path, index=False)
    print(
        f"Wrote {len(dataset)} rows to {output_path} "
        f"(dropped_missing_market_odds={dropped_missing_market_odds})"
    )


if __name__ == "__main__":
    main()
