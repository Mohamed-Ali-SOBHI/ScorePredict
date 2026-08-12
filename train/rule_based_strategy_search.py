from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy_search_common import MARKET_PROB_COLS_MODEL_ORDER, OUTCOME_INDEX


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = SCRIPT_DIR / "dataset_home.csv"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output" / "rule_based_protocol"
LEAGUES = ["EPL", "Bundesliga", "La_liga", "Ligue_1", "Serie_A"]


@dataclass(frozen=True)
class RuleFamily:
    category: str
    bet_league: str
    odds_min: float
    odds_max: float
    params: dict[str, float]

    @property
    def name(self) -> str:
        param_bits = ",".join(f"{key}={value:g}" for key, value in sorted(self.params.items()))
        return (
            f"rule={self.category}|bet={self.bet_league or 'ALL'}|outcome=draw|"
            f"odds=[{self.odds_min:.2f},{self.odds_max:.2f})|{param_bits}"
        )


@dataclass(frozen=True)
class Fold:
    val_season: int
    test_season: int

    @property
    def label(self) -> str:
        return f"val{self.val_season}_test{self.test_season}"


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward benchmark for simple rule-based draw strategies."
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start-val-season", type=int, default=2021)
    parser.add_argument("--end-val-season", type=int, default=2024)
    parser.add_argument("--min-val-bets", type=int, default=25)
    parser.add_argument("--min-val-roi", type=float, default=0.02)
    parser.add_argument("--max-strategies", type=int, default=4)
    parser.add_argument("--max-val-overlap", type=float, default=0.35)
    parser.add_argument("--selection-min-roi", type=float, default=0.0)
    parser.add_argument("--min-total-test-bets", type=int, default=80)
    parser.add_argument("--max-negative-folds", type=int, default=1)
    parser.add_argument(
        "--include-categories",
        default="",
        help="Comma-separated rule categories to include. Empty means all categories.",
    )
    parser.add_argument(
        "--include-bet-leagues",
        default="",
        help="Comma-separated rule scopes to include. Use ALL for cross-league rules.",
    )
    parser.add_argument(
        "--exclude-bet-leagues",
        default="",
        help="Comma-separated rule scopes to exclude. Use ALL for cross-league rules.",
    )
    parser.add_argument(
        "--include-data-leagues",
        default="",
        help="Comma-separated data leagues to include before building folds.",
    )
    parser.add_argument(
        "--exclude-data-leagues",
        default="",
        help="Comma-separated data leagues to exclude before building folds.",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna(subset=["target"]).copy()


def csv_values(raw_values: str) -> set[str]:
    return {value.strip() for value in raw_values.split(",") if value.strip()}


def filter_dataset_leagues(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    include_leagues = csv_values(args.include_data_leagues)
    exclude_leagues = csv_values(args.exclude_data_leagues)
    if include_leagues:
        df = df[df["league"].isin(include_leagues)].copy()
    if exclude_leagues:
        df = df[~df["league"].isin(exclude_leagues)].copy()
    if df.empty:
        raise ValueError("No rows left after data league filtering")
    return df


def rule_scope(rule: RuleFamily) -> str:
    return rule.bet_league or "ALL"


def filter_rules(rules: list[RuleFamily], args: argparse.Namespace) -> list[RuleFamily]:
    include_categories = csv_values(args.include_categories)
    include_bet_leagues = csv_values(args.include_bet_leagues)
    exclude_bet_leagues = csv_values(args.exclude_bet_leagues)
    if include_categories:
        rules = [rule for rule in rules if rule.category in include_categories]
    if include_bet_leagues:
        rules = [rule for rule in rules if rule_scope(rule) in include_bet_leagues]
    if exclude_bet_leagues:
        rules = [rule for rule in rules if rule_scope(rule) not in exclude_bet_leagues]
    return rules


def build_folds(df: pd.DataFrame, start_val_season: int, end_val_season: int) -> list[Fold]:
    seasons = {int(value) for value in df["season"].dropna().unique()}
    folds = []
    for val_season in range(start_val_season, end_val_season + 1):
        test_season = val_season + 1
        if val_season in seasons and test_season in seasons:
            folds.append(Fold(val_season=val_season, test_season=test_season))
    if not folds:
        raise ValueError("No valid folds found")
    return folds


def base_draw_bets(df: pd.DataFrame) -> pd.DataFrame:
    bets = df.copy()
    selected_odds = pd.to_numeric(bets["market_draw_odds_open"], errors="coerce")
    bets["selected_outcome"] = "draw"
    bets["selected_odds"] = selected_odds
    bets["market_probability"] = pd.to_numeric(bets["market_draw_prob_open"], errors="coerce")
    bets["predicted_probability"] = np.nan
    bets["edge"] = np.nan
    bets["expected_value"] = np.nan
    bets["raw_model_probability"] = np.nan
    bets["value_score"] = np.nan
    bets["raw_expected_value"] = np.nan
    bets["probability_note"] = "rule_based_no_model_probability"
    bets["won_bet"] = bets["target"].astype(int).to_numpy() == OUTCOME_INDEX["draw"]
    bets["profit"] = np.where(bets["won_bet"], bets["selected_odds"] - 1.0, -1.0)

    valid_mask = np.isfinite(selected_odds) & (selected_odds > 1.0)
    bets = bets[valid_mask].copy()

    market_probs = bets[MARKET_PROB_COLS_MODEL_ORDER].to_numpy()
    market_fav_idx = market_probs.argmax(axis=1)
    bets["bet_is_market_favorite"] = market_fav_idx == OUTCOME_INDEX["draw"]
    bets["bet_key"] = bets["match_id"].astype(str) + "|draw"
    return bets


def num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def apply_rule(base: pd.DataFrame, rule: RuleFamily) -> pd.DataFrame:
    mask = (num(base, "selected_odds") >= rule.odds_min) & (num(base, "selected_odds") < rule.odds_max)
    if rule.bet_league:
        mask &= base["league"] == rule.bet_league
    mask &= ~base["bet_is_market_favorite"]

    p = rule.params
    market_gap = num(base, "draw_market_home_away_gap_open").abs()
    fav_prob = num(base, "market_favorite_prob_open")
    fav_gap = num(base, "market_favorite_gap_open")
    entropy = num(base, "market_entropy_open")
    triplet_std = num(base, "draw_market_triplet_std_open")
    elo_gap = num(base, "draw_abs_elo_gap")
    xg_gap = num(base, "draw_abs_xG_advantage_5_carry")
    def_gap = num(base, "draw_abs_defensive_advantage_5_carry")
    form_gap = num(base, "draw_abs_relative_form_5_carry")
    total_xg = num(base, "draw_total_xG_last_5_carry")
    total_xga = num(base, "draw_total_xG_against_last_5_carry")
    combined_draw = num(base, "draw_combined_draw_rate_10_carry")
    draw_rate_gap = num(base, "draw_draw_rate_gap_10_carry").abs()
    prev_draw_sum = num(base, "prev_season_draw_rate") + num(base, "opponent_prev_season_draw_rate")

    if rule.category == "market_shape":
        mask &= market_gap <= p["market_gap_max"]
        mask &= fav_prob <= p["favorite_prob_max"]
        mask &= entropy >= p["entropy_min"]
        mask &= triplet_std <= p["triplet_std_max"]
    elif rule.category == "parity_draw":
        mask &= elo_gap <= p["elo_gap_max"]
        mask &= xg_gap <= p["xg_gap_max"]
        mask &= def_gap <= p["def_gap_max"]
        mask &= form_gap <= p["form_gap_max"]
        mask &= market_gap <= p["market_gap_max"]
    elif rule.category == "low_event_parity":
        mask &= elo_gap <= p["elo_gap_max"]
        mask &= xg_gap <= p["xg_gap_max"]
        mask &= def_gap <= p["def_gap_max"]
        mask &= market_gap <= p["market_gap_max"]
        mask &= total_xg <= p["total_xg_max"]
        mask &= total_xga <= p["total_xga_max"]
    elif rule.category == "false_favorite":
        mask &= fav_prob >= p["favorite_prob_min"]
        mask &= fav_prob <= p["favorite_prob_max"]
        mask &= fav_gap >= p["favorite_gap_min"]
        mask &= fav_gap <= p["favorite_gap_max"]
        mask &= elo_gap <= p["elo_gap_max"]
        mask &= xg_gap <= p["xg_gap_max"]
        mask &= def_gap <= p["def_gap_max"]
    elif rule.category == "league_draw_regime":
        mask &= prev_draw_sum >= p["prev_draw_sum_min"]
        mask &= combined_draw >= p["combined_draw_min"]
        mask &= draw_rate_gap <= p["draw_rate_gap_max"]
        mask &= triplet_std <= p["triplet_std_max"]
        mask &= market_gap <= p["market_gap_max"]
    elif rule.category == "underdog_resistance":
        mask &= fav_prob >= p["favorite_prob_min"]
        mask &= fav_gap >= p["favorite_gap_min"]
        mask &= xg_gap <= p["xg_gap_max"]
        mask &= def_gap <= p["def_gap_max"]
        mask &= combined_draw >= p["combined_draw_min"]
    else:
        raise ValueError(f"Unknown rule category: {rule.category}")

    bets = base[mask].copy()
    bets["strategy_name"] = rule.name
    bets["rule_category"] = rule.category
    return bets


def summarize_bets(bets: pd.DataFrame, prefix: str) -> dict[str, float | int | None]:
    if bets.empty:
        return {
            f"{prefix}_bets": 0,
            f"{prefix}_roi": None,
            f"{prefix}_profit": 0.0,
            f"{prefix}_hit_rate": None,
            f"{prefix}_avg_odds": None,
        }
    return {
        f"{prefix}_bets": int(len(bets)),
        f"{prefix}_roi": float(bets["profit"].mean()),
        f"{prefix}_profit": float(bets["profit"].sum()),
        f"{prefix}_hit_rate": float(bets["won_bet"].mean()),
        f"{prefix}_avg_odds": float(bets["selected_odds"].mean()),
    }


def build_rule_families() -> list[RuleFamily]:
    odds_ranges = [(2.2, 4.0), (3.2, 4.8), (4.0, 10.0), (2.0, 10.0)]
    leagues = ["", *LEAGUES]
    rules: list[RuleFamily] = []

    for league in leagues:
        for odds_min, odds_max in odds_ranges:
            for market_gap_max in [0.28, 0.45]:
                for favorite_prob_max in [0.55, 0.70]:
                    for entropy_min in [0.98, 1.05]:
                        for triplet_std_max in [0.18, 0.30]:
                            rules.append(
                                RuleFamily(
                                    "market_shape",
                                    league,
                                    odds_min,
                                    odds_max,
                                    {
                                        "market_gap_max": market_gap_max,
                                        "favorite_prob_max": favorite_prob_max,
                                        "entropy_min": entropy_min,
                                        "triplet_std_max": triplet_std_max,
                                    },
                                )
                            )

            for elo_gap_max in [75.0, 150.0]:
                for xg_gap_max in [0.55, 0.85]:
                    for def_gap_max in [0.55, 0.85]:
                        for form_gap_max in [5.5, 8.0]:
                            for market_gap_max in [0.35, 0.55]:
                                rules.append(
                                    RuleFamily(
                                        "parity_draw",
                                        league,
                                        odds_min,
                                        odds_max,
                                        {
                                            "elo_gap_max": elo_gap_max,
                                            "xg_gap_max": xg_gap_max,
                                            "def_gap_max": def_gap_max,
                                            "form_gap_max": form_gap_max,
                                            "market_gap_max": market_gap_max,
                                        },
                                    )
                                )

            for elo_gap_max in [120.0, 170.0]:
                for xg_gap_max in [0.55, 0.85]:
                    for def_gap_max in [0.85]:
                        for market_gap_max in [0.35, 0.55]:
                            for total_xg_max in [2.9, 3.2]:
                                for total_xga_max in [3.05]:
                                    rules.append(
                                        RuleFamily(
                                            "low_event_parity",
                                            league,
                                            odds_min,
                                            odds_max,
                                            {
                                                "elo_gap_max": elo_gap_max,
                                                "xg_gap_max": xg_gap_max,
                                                "def_gap_max": def_gap_max,
                                                "market_gap_max": market_gap_max,
                                                "total_xg_max": total_xg_max,
                                                "total_xga_max": total_xga_max,
                                            },
                                        )
                                    )

            for favorite_prob_min in [0.50, 0.55]:
                for favorite_prob_max in [0.75]:
                    for favorite_gap_min in [0.12, 0.22]:
                        for favorite_gap_max in [0.60]:
                            for elo_gap_max in [150.0, 200.0]:
                                for xg_gap_max in [0.85, 1.10]:
                                    for def_gap_max in [0.85]:
                                        rules.append(
                                            RuleFamily(
                                                "false_favorite",
                                                league,
                                                odds_min,
                                                odds_max,
                                                {
                                                    "favorite_prob_min": favorite_prob_min,
                                                    "favorite_prob_max": favorite_prob_max,
                                                    "favorite_gap_min": favorite_gap_min,
                                                    "favorite_gap_max": favorite_gap_max,
                                                    "elo_gap_max": elo_gap_max,
                                                    "xg_gap_max": xg_gap_max,
                                                    "def_gap_max": def_gap_max,
                                                },
                                            )
                                        )

            for prev_draw_sum_min in [0.42, 0.52]:
                for combined_draw_min in [0.30, 0.40]:
                    for draw_rate_gap_max in [0.30, 0.45]:
                        for triplet_std_max in [0.26, 0.34]:
                            for market_gap_max in [0.45]:
                                rules.append(
                                    RuleFamily(
                                        "league_draw_regime",
                                        league,
                                        odds_min,
                                        odds_max,
                                        {
                                            "prev_draw_sum_min": prev_draw_sum_min,
                                            "combined_draw_min": combined_draw_min,
                                            "draw_rate_gap_max": draw_rate_gap_max,
                                            "triplet_std_max": triplet_std_max,
                                            "market_gap_max": market_gap_max,
                                        },
                                    )
                                )

            for favorite_prob_min in [0.50, 0.60]:
                for favorite_gap_min in [0.12, 0.24]:
                    for xg_gap_max in [0.85, 1.10]:
                        for def_gap_max in [0.65, 0.90]:
                            for combined_draw_min in [0.25, 0.35]:
                                rules.append(
                                    RuleFamily(
                                        "underdog_resistance",
                                        league,
                                        odds_min,
                                        odds_max,
                                        {
                                            "favorite_prob_min": favorite_prob_min,
                                            "favorite_gap_min": favorite_gap_min,
                                            "xg_gap_max": xg_gap_max,
                                            "def_gap_max": def_gap_max,
                                            "combined_draw_min": combined_draw_min,
                                        },
                                    )
                                )
    return rules


def overlap_ratio(candidate_keys: set[str], selected_keys: set[str]) -> float:
    if not candidate_keys:
        return 0.0
    return len(candidate_keys & selected_keys) / float(len(candidate_keys))


def select_portfolio(
    candidates: list[dict[str, Any]],
    *,
    max_strategies: int,
    max_overlap: float,
    selection_min_roi: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    ordered = sorted(
        candidates,
        key=lambda item: (item["val_roi"], item["val_profit"], item["val_bets"]),
        reverse=True,
    )
    for candidate in ordered:
        if candidate["val_roi"] is None or candidate["val_roi"] < selection_min_roi:
            continue
        candidate_keys = set(candidate["val_bets_df"]["bet_key"].astype(str))
        overlap = overlap_ratio(candidate_keys, selected_keys)
        candidate["portfolio_selection_overlap"] = overlap
        if overlap > max_overlap:
            continue
        selected.append(candidate)
        selected_keys |= candidate_keys
        if len(selected) >= max_strategies:
            break
    return selected


def combine_portfolio_bets(selected: list[dict[str, Any]], split_name: str) -> pd.DataFrame:
    frames = []
    for index, candidate in enumerate(selected):
        bets = candidate[f"{split_name}_bets_df"]
        if bets.empty:
            continue
        tagged = bets.copy()
        tagged["strategy_name"] = candidate["strategy_name"]
        tagged["rule_category"] = candidate["rule_category"]
        tagged["portfolio_order"] = index
        frames.append(tagged)
    if not frames:
        return pd.DataFrame()
    all_bets = pd.concat(frames, ignore_index=True)
    strategy_names = (
        all_bets.groupby("bet_key", sort=False)["strategy_name"]
        .agg(lambda values: "|".join(dict.fromkeys(values)))
        .rename("strategy_names")
    )
    deduped = (
        all_bets.sort_values(["bet_key", "portfolio_order"])
        .drop_duplicates(subset=["bet_key"], keep="first")
        .copy()
    )
    return deduped.merge(strategy_names, on="bet_key", how="left", validate="one_to_one")


def evaluate_fold(
    val_base: pd.DataFrame,
    test_base: pd.DataFrame,
    rules: list[RuleFamily],
    *,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame]:
    candidates: list[dict[str, Any]] = []
    for rule in rules:
        val_bets = apply_rule(val_base, rule)
        if len(val_bets) < args.min_val_bets:
            continue
        val_summary = summarize_bets(val_bets, "val")
        if val_summary["val_roi"] is None or val_summary["val_roi"] < args.min_val_roi:
            continue
        test_bets = apply_rule(test_base, rule)
        candidate = {
            "strategy_name": rule.name,
            "rule_category": rule.category,
            "bet_league": rule.bet_league or "ALL",
            "outcome": "draw",
            "odds_min": rule.odds_min,
            "odds_max": rule.odds_max,
            "market_favorite_mode": "nonfavorite",
            "params": json.dumps(rule.params, sort_keys=True),
            "val_bets_df": val_bets.copy(),
            "test_bets_df": test_bets.copy(),
            **val_summary,
            **summarize_bets(test_bets, "test"),
        }
        candidates.append(candidate)

    selected = select_portfolio(
        candidates,
        max_strategies=args.max_strategies,
        max_overlap=args.max_val_overlap,
        selection_min_roi=args.selection_min_roi,
    )
    portfolio_test = combine_portfolio_bets(selected, "test")
    selected_names = {candidate["strategy_name"] for candidate in selected}
    selected_rows = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item["val_roi"], item["val_profit"], item["val_bets"]),
        reverse=True,
    ):
        selected_rows.append(
            {
                "selected_for_portfolio": candidate["strategy_name"] in selected_names,
                **{
                    key: value
                    for key, value in candidate.items()
                    if not key.endswith("_df")
                },
            }
        )
    summary = summarize_bets(portfolio_test, "test")
    registry_metrics = {
        "selected_strategy_count": len(selected),
        "test_bets": summary["test_bets"],
        "test_wins": int(portfolio_test["won_bet"].sum()) if not portfolio_test.empty else 0,
        "test_profit": summary["test_profit"],
        "test_roi": summary["test_roi"],
        "test_hit_rate": summary["test_hit_rate"],
        "test_avg_odds": summary["test_avg_odds"],
    }
    return registry_metrics, selected_rows, portfolio_test


def aggregate_leaderboard(
    registry: pd.DataFrame,
    *,
    expected_folds: int,
    min_total_test_bets: int,
    max_negative_folds: int,
) -> pd.DataFrame:
    completed = registry[registry["status"] == "ok"].copy()
    total_bets = int(completed["test_bets"].sum())
    total_wins = int(completed["test_wins"].sum())
    total_profit = float(completed["test_profit"].sum())
    rois = completed["test_roi"].dropna()
    mean_roi = float(rois.mean()) if len(rois) else None
    std_roi = float(rois.std(ddof=0)) if len(rois) > 1 else 0.0 if len(rois) else None
    negative_folds = int((completed["test_profit"] < 0).sum())
    eligible = (
        len(completed) == expected_folds
        and total_bets >= min_total_test_bets
        and negative_folds <= max_negative_folds
    )
    row = {
        "rank": 1,
        "experiment_name": "rule_based_draw_protocol",
        "eligible": bool(eligible),
        "completed_folds": int(len(completed)),
        "failed_folds": int(len(registry) - len(completed)),
        "total_test_bets": total_bets,
        "total_test_wins": total_wins,
        "total_test_profit": total_profit,
        "pooled_test_roi": total_profit / total_bets if total_bets else None,
        "pooled_hit_rate": total_wins / total_bets if total_bets else None,
        "mean_fold_roi": mean_roi,
        "median_fold_roi": float(rois.median()) if len(rois) else None,
        "min_fold_roi": float(rois.min()) if len(rois) else None,
        "max_fold_roi": float(rois.max()) if len(rois) else None,
        "std_fold_roi": std_roi,
        "risk_adjusted_roi": mean_roi - std_roi if mean_roi is not None and std_roi is not None else None,
        "profitable_folds": int((completed["test_profit"] > 0).sum()),
        "negative_folds": negative_folds,
        "zero_bet_folds": int((completed["test_bets"] == 0).sum()),
    }
    return pd.DataFrame([row])


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        values = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            elif value is None:
                values.append("")
            else:
                values.append(str(value))
        body.append("| " + " | ".join(values) + " |")
    return "\n".join([header, sep, *body])


def write_report(
    output_path: Path,
    *,
    registry: pd.DataFrame,
    leaderboard: pd.DataFrame,
    selected: pd.DataFrame,
    args: argparse.Namespace,
    rule_count: int,
) -> None:
    top_selected = selected[selected["selected_for_portfolio"].astype(bool)].copy()
    top_selected = top_selected[
        [
            "fold",
            "rule_category",
            "bet_league",
            "odds_min",
            "odds_max",
            "val_bets",
            "val_roi",
            "test_bets",
            "test_roi",
            "test_profit",
        ]
    ].to_dict(orient="records")
    lines = [
        "# Rule-based draw protocol",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Protocol",
        "",
        "- No model probabilities are used.",
        "- Rules are selected on the validation season only.",
        "- The following season is tested without using its results for selection.",
        f"- Candidate rules searched per fold: `{rule_count}`",
        f"- Min validation bets: `{args.min_val_bets}`",
        f"- Min validation ROI: `{args.min_val_roi:.2f}`",
        f"- Max strategies per fold: `{args.max_strategies}`",
        f"- Included categories: `{args.include_categories or 'ALL'}`",
        f"- Included rule scopes: `{args.include_bet_leagues or 'ALL'}`",
        f"- Excluded rule scopes: `{args.exclude_bet_leagues or 'none'}`",
        f"- Included data leagues: `{args.include_data_leagues or 'ALL'}`",
        f"- Excluded data leagues: `{args.exclude_data_leagues or 'none'}`",
        "",
        "## Leaderboard",
        "",
        markdown_table(
            leaderboard.to_dict(orient="records"),
            [
                "experiment_name",
                "eligible",
                "total_test_bets",
                "total_test_profit",
                "pooled_test_roi",
                "negative_folds",
                "risk_adjusted_roi",
            ],
        ),
        "",
        "## Folds",
        "",
        markdown_table(
            registry.to_dict(orient="records"),
            ["fold", "val_season", "test_season", "test_bets", "test_profit", "test_roi", "selected_strategy_count"],
        ),
        "",
        "## Selected Rules",
        "",
        markdown_table(
            top_selected,
            ["fold", "rule_category", "bet_league", "odds_min", "odds_max", "val_bets", "val_roi", "test_bets", "test_roi", "test_profit"],
        ),
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    data_path = resolve_path(args.data)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    folds_dir = output_dir / "folds"
    folds_dir.mkdir(parents=True, exist_ok=True)

    df = filter_dataset_leagues(load_dataset(data_path), args)
    folds = build_folds(df, args.start_val_season, args.end_val_season)
    rules = filter_rules(build_rule_families(), args)
    if not rules:
        raise ValueError("No rules left after category filtering")
    print({"rules": len(rules), "folds": [fold.label for fold in folds], "output_dir": str(output_dir)})

    registry_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    best_bets_frames = []
    for fold in folds:
        val_base = base_draw_bets(df[df["season"] == fold.val_season].copy())
        test_base = base_draw_bets(df[df["season"] == fold.test_season].copy())
        metrics, fold_selected, fold_bets = evaluate_fold(val_base, test_base, rules, args=args)
        for row in fold_selected:
            row.update({"fold": fold.label, "val_season": fold.val_season, "test_season": fold.test_season})
        selected_rows.extend(fold_selected)
        if not fold_bets.empty:
            meta = pd.DataFrame(
                {
                    "experiment_name": "rule_based_draw_protocol",
                    "fold": fold.label,
                    "val_season": fold.val_season,
                    "test_season": fold.test_season,
                },
                index=fold_bets.index,
            )
            best_bets_frames.append(pd.concat([meta, fold_bets], axis=1))
        fold_bets_path = folds_dir / f"rule_based_draw_protocol_{fold.label}_bets.csv"
        fold_bets.to_csv(fold_bets_path, index=False)
        registry_row = {
            "experiment_name": "rule_based_draw_protocol",
            "fold": fold.label,
            "val_season": fold.val_season,
            "test_season": fold.test_season,
            "status": "ok",
            "bets_path": str(fold_bets_path),
            **metrics,
        }
        registry_rows.append(registry_row)
        print(
            {
                "fold": fold.label,
                "selected_strategy_count": metrics["selected_strategy_count"],
                "test_bets": metrics["test_bets"],
                "test_profit": metrics["test_profit"],
                "test_roi": metrics["test_roi"],
            }
        )

    registry = pd.DataFrame(registry_rows)
    selected = pd.DataFrame(selected_rows)
    leaderboard = aggregate_leaderboard(
        registry,
        expected_folds=len(folds),
        min_total_test_bets=args.min_total_test_bets,
        max_negative_folds=args.max_negative_folds,
    )
    best_bets = pd.concat(best_bets_frames, ignore_index=True) if best_bets_frames else pd.DataFrame()

    registry.to_csv(output_dir / "experiment_registry.csv", index=False)
    selected.to_csv(output_dir / "selected_strategies.csv", index=False)
    leaderboard.to_csv(output_dir / "experiment_leaderboard.csv", index=False)
    best_bets.to_csv(output_dir / "best_strategy_bets.csv", index=False)
    write_report(
        output_dir / "experimental_protocol_report.md",
        registry=registry,
        leaderboard=leaderboard,
        selected=selected,
        args=args,
        rule_count=len(rules),
    )
    (output_dir / "experimental_protocol_report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "rule_count": len(rules),
                "registry": registry.to_dict(orient="records"),
                "leaderboard": leaderboard.to_dict(orient="records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        {
            "leaderboard": str(output_dir / "experiment_leaderboard.csv"),
            "report": str(output_dir / "experimental_protocol_report.md"),
            "best_strategy_bets": str(output_dir / "best_strategy_bets.csv"),
            "best_bets_count": len(best_bets),
        }
    )


if __name__ == "__main__":
    main()
