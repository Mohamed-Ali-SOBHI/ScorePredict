from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = SCRIPT_DIR / "dataset_home.csv"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output" / "experimental_protocol"
STRATEGY_SEARCH_SCRIPT = SCRIPT_DIR / "portfolio_strategy_search.py"


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    description: str
    model_variants: str
    outcomes: str
    train_scopes: str
    bet_leagues: str
    odds_ranges: str
    market_favorite_modes: str
    profile_filters: str = "any"
    threshold_start: float = 0.10
    threshold_stop: float = 0.70
    threshold_step: float = 0.05
    edge_values: str = "0.0,0.02,0.04,0.06,0.08,0.10"


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
        description=(
            "Run a walk-forward experimental protocol over several seasons and "
            "aggregate the strategy-search results."
        )
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", choices=["quick", "standard", "wide"], default="standard")
    parser.add_argument("--include-experiments", default="")
    parser.add_argument("--exclude-experiments", default="")
    parser.add_argument("--start-val-season", type=int, default=2021)
    parser.add_argument("--end-val-season", type=int, default=2024)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--n-estimators", type=int, default=350)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-val-bets", type=int, default=25)
    parser.add_argument("--min-val-roi", type=float, default=0.02)
    parser.add_argument("--max-strategies", type=int, default=4)
    parser.add_argument("--max-val-overlap", type=float, default=0.35)
    parser.add_argument("--selection-min-roi", type=float, default=0.0)
    parser.add_argument("--min-total-test-bets", type=int, default=80)
    parser.add_argument("--max-negative-folds", type=int, default=1)
    parser.add_argument("--portfolio-selection-split", choices=["val", "test"], default="val")
    parser.add_argument("--test-fit-scope", choices=["train", "pretest"], default="train")
    parser.add_argument("--include-algo-features", action="store_true")
    parser.add_argument("--include-closing-market-features", action="store_true")
    parser.add_argument("--include-consensus-market-features", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_experiment_specs(profile: str) -> list[ExperimentSpec]:
    leagues = "EPL,Bundesliga,La_liga,Ligue_1,Serie_A"
    draw_ranges = "2.20:4.00,4.00:10.00,2.00:10.00"
    all_ranges = "1.30:2.20,2.20:4.00,4.00:10.00,2.00:10.00"

    specs = [
        ExperimentSpec(
            name="draw_multiclass_nonfavorite",
            description="Multiclass XGBoost, draw-only value bets, no market favorites.",
            model_variants="multiclass",
            outcomes="draw",
            train_scopes="ALL,LOCAL",
            bet_leagues=leagues,
            odds_ranges=draw_ranges,
            market_favorite_modes="nonfavorite",
        ),
        ExperimentSpec(
            name="draw_binary_nonfavorite",
            description="Binary draw XGBoost, draw-only value bets, no market favorites.",
            model_variants="draw_binary",
            outcomes="draw",
            train_scopes="ALL,LOCAL",
            bet_leagues=leagues,
            odds_ranges=draw_ranges,
            market_favorite_modes="nonfavorite",
        ),
    ]

    if profile in {"standard", "wide"}:
        specs.extend(
            [
                ExperimentSpec(
                    name="draw_mixed_nonfavorite",
                    description="Multiclass and binary draw models compete in one portfolio.",
                    model_variants="multiclass,draw_binary",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                ),
                ExperimentSpec(
                    name="multiclass_all_outcomes_value",
                    description="Multiclass model can select home, draw, or away outcomes.",
                    model_variants="multiclass",
                    outcomes="home_win,draw,away_win",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=all_ranges,
                    market_favorite_modes="favorite,nonfavorite",
                ),
            ]
        )

    if profile == "wide":
        specs.extend(
            [
                ExperimentSpec(
                    name="away_underdog_value",
                    description="Multiclass away-win value bets where away is not the market favorite.",
                    model_variants="multiclass",
                    outcomes="away_win",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges="2.20:4.00,4.00:10.00,2.00:10.00",
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.10,
                    threshold_stop=0.80,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10,0.12",
                ),
                ExperimentSpec(
                    name="seriea_away_underdog_value",
                    description="Serie A away-win value bets where away is not the market favorite.",
                    model_variants="multiclass",
                    outcomes="away_win",
                    train_scopes="ALL,LOCAL",
                    bet_leagues="Serie_A",
                    odds_ranges="2.20:4.00,4.00:10.00,2.00:10.00",
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.10,
                    threshold_stop=0.80,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10,0.12",
                ),
                ExperimentSpec(
                    name="bundesliga_long_draw",
                    description="Bundesliga draw value bets restricted to long nonfavorite draw prices.",
                    model_variants="multiclass",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues="Bundesliga",
                    odds_ranges="4.00:10.00",
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.10,
                    threshold_stop=0.85,
                    threshold_step=0.05,
                    edge_values="0.04,0.06,0.08,0.10,0.12,0.15",
                ),
                ExperimentSpec(
                    name="draw_consensus_nonfavorite",
                    description="Draw bets where multiclass and binary draw models agree conservatively.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="draw_multiclass_high_odds",
                    description="Multiclass draw bets restricted to the high-odds draw bucket.",
                    model_variants="multiclass",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges="4.00:10.00",
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.15,
                    threshold_stop=0.85,
                    threshold_step=0.05,
                    edge_values="0.04,0.06,0.08,0.10,0.12,0.15",
                ),
                ExperimentSpec(
                    name="draw_binary_high_odds",
                    description="Binary draw model restricted to the high-odds draw bucket.",
                    model_variants="draw_binary",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges="4.00:10.00",
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.15,
                    threshold_stop=0.85,
                    threshold_step=0.05,
                    edge_values="0.04,0.06,0.08,0.10,0.12,0.15",
                ),
                ExperimentSpec(
                    name="draw_low_event_parity",
                    description="Conservative draw consensus in low-event, team-parity match profiles.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="low_event_parity",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="false_favorite_draw",
                    description="Draw consensus where the market shows a clear favorite but pre-match parity features disagree.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="false_favorite_draw",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="draw_consensus_strict",
                    description="Draw consensus with both draw models above market and low model disagreement.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="strict_consensus",
                    threshold_start=0.02,
                    threshold_stop=0.50,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10,0.12",
                ),
                ExperimentSpec(
                    name="league_regime_draw",
                    description="Draw consensus in matches with high historical draw tendencies and balanced market shape.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="league_regime_draw",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="favorite_fatigue_draw",
                    description="Draw consensus against market favorites carrying a rest disadvantage.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="favorite_fatigue_trap",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="underdog_resistance_draw",
                    description="Draw consensus where the underdog profile looks defensively resistant instead of just cheap.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="underdog_resistance",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="draw_anti_overconfidence",
                    description="Draw consensus that rejects extreme raw-model edges likely caused by miscalibration.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters="anti_overconfidence",
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="meta_draw_profile_portfolio",
                    description="Meta portfolio allowing several innovative draw profile filters to compete on validation.",
                    model_variants="draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    profile_filters=(
                        "low_event_parity,false_favorite_draw,strict_consensus,"
                        "league_regime_draw,favorite_fatigue_trap,underdog_resistance,anti_overconfidence"
                    ),
                    threshold_start=0.05,
                    threshold_stop=0.55,
                    threshold_step=0.05,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="logistic_draw_consensus_nonfavorite",
                    description="Logistic regression consensus between multiclass and binary draw models.",
                    model_variants="logistic_draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="extra_trees_draw_consensus_nonfavorite",
                    description="ExtraTrees consensus between multiclass and binary draw models.",
                    model_variants="extra_trees_draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="hist_gradient_draw_consensus_nonfavorite",
                    description="Histogram gradient boosting consensus between multiclass and binary draw models.",
                    model_variants="hist_gradient_draw_consensus",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="logistic_draw_binary_nonfavorite",
                    description="Logistic regression binary draw model.",
                    model_variants="logistic_draw_binary",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="extra_trees_draw_binary_nonfavorite",
                    description="ExtraTrees binary draw model.",
                    model_variants="extra_trees_draw_binary",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
                ExperimentSpec(
                    name="hist_gradient_draw_binary_nonfavorite",
                    description="Histogram gradient boosting binary draw model.",
                    model_variants="hist_gradient_draw_binary",
                    outcomes="draw",
                    train_scopes="ALL,LOCAL",
                    bet_leagues=leagues,
                    odds_ranges=draw_ranges,
                    market_favorite_modes="nonfavorite",
                    threshold_start=0.02,
                    threshold_stop=0.55,
                    threshold_step=0.04,
                    edge_values="0.0,0.02,0.04,0.06,0.08,0.10",
                ),
            ]
        )

    return specs


def filter_experiment_specs(
    specs: list[ExperimentSpec],
    *,
    include_experiments: str,
    exclude_experiments: str,
) -> list[ExperimentSpec]:
    include = {value.strip() for value in include_experiments.split(",") if value.strip()}
    exclude = {value.strip() for value in exclude_experiments.split(",") if value.strip()}
    filtered = [
        spec
        for spec in specs
        if (not include or spec.name in include) and spec.name not in exclude
    ]
    if not filtered:
        raise ValueError("No experiments left after include/exclude filtering")
    unknown_include = include - {spec.name for spec in specs}
    if unknown_include:
        raise ValueError(f"Unknown include experiments: {sorted(unknown_include)}")
    return filtered


def load_dataset_profile(data_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.read_csv(data_path, usecols=["match_id", "date", "league", "season", "target"])
    df["date"] = pd.to_datetime(df["date"])
    completed = df.dropna(subset=["target"]).copy()
    season_counts = (
        completed.groupby("season")["match_id"]
        .nunique()
        .sort_index()
        .astype(int)
        .to_dict()
    )
    profile = {
        "rows": int(len(completed)),
        "matches": int(completed["match_id"].nunique()),
        "min_date": completed["date"].min().isoformat(),
        "max_date": completed["date"].max().isoformat(),
        "min_season": int(completed["season"].min()),
        "max_season": int(completed["season"].max()),
        "season_match_counts": {str(int(k)): int(v) for k, v in season_counts.items()},
        "leagues": sorted(str(value) for value in completed["league"].dropna().unique()),
    }
    return completed, profile


def build_folds(df: pd.DataFrame, start_val_season: int, end_val_season: int) -> list[Fold]:
    available = {int(value) for value in df["season"].dropna().unique()}
    folds = []
    for val_season in range(start_val_season, end_val_season + 1):
        test_season = val_season + 1
        if val_season in available and test_season in available:
            folds.append(Fold(val_season=val_season, test_season=test_season))
    if not folds:
        raise ValueError("No valid folds found for the requested season range")
    return folds


def command_for_run(
    *,
    python_exe: str,
    data_path: Path,
    spec: ExperimentSpec,
    fold: Fold,
    args: argparse.Namespace,
    summary_path: Path,
    bets_path: Path,
    seed: int,
) -> list[str]:
    command = [
        python_exe,
        str(STRATEGY_SEARCH_SCRIPT),
        "--data",
        str(data_path),
        "--val-season",
        str(fold.val_season),
        "--test-season",
        str(fold.test_season),
        "--trials",
        str(args.trials),
        "--seed",
        str(seed),
        "--n-estimators",
        str(args.n_estimators),
        "--model-variants",
        spec.model_variants,
        "--train-scopes",
        spec.train_scopes,
        "--bet-leagues",
        spec.bet_leagues,
        "--outcomes",
        spec.outcomes,
        "--odds-ranges",
        spec.odds_ranges,
        "--market-favorite-modes",
        spec.market_favorite_modes,
        "--profile-filters",
        spec.profile_filters,
        "--threshold-start",
        str(spec.threshold_start),
        "--threshold-stop",
        str(spec.threshold_stop),
        "--threshold-step",
        str(spec.threshold_step),
        "--edge-values",
        spec.edge_values,
        "--min-val-bets",
        str(args.min_val_bets),
        "--min-val-roi",
        str(args.min_val_roi),
        "--max-strategies",
        str(args.max_strategies),
        "--max-val-overlap",
        str(args.max_val_overlap),
        "--portfolio-selection-split",
        args.portfolio_selection_split,
        "--selection-min-roi",
        str(args.selection_min_roi),
        "--test-fit-scope",
        args.test_fit_scope,
        "--export-summary",
        str(summary_path),
        "--export-bets",
        str(bets_path),
    ]
    if args.include_algo_features:
        command.append("--include-algo-features")
    if args.include_closing_market_features:
        command.append("--include-closing-market-features")
    if args.include_consensus_market_features:
        command.append("--include-consensus-market-features")
    return command


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def summarize_bets(path: Path) -> dict[str, Any]:
    bets = read_csv_or_empty(path)
    if bets.empty:
        return {
            "test_bets": 0,
            "test_wins": 0,
            "test_profit": 0.0,
            "test_roi": None,
            "test_hit_rate": None,
            "test_avg_odds": None,
        }

    profit = float(bets["profit"].sum())
    bet_count = int(len(bets))
    wins = int(bets["won_bet"].sum()) if "won_bet" in bets.columns else None
    return {
        "test_bets": bet_count,
        "test_wins": wins,
        "test_profit": profit,
        "test_roi": profit / bet_count if bet_count else None,
        "test_hit_rate": wins / bet_count if wins is not None and bet_count else None,
        "test_avg_odds": float(bets["selected_odds"].mean()) if "selected_odds" in bets.columns else None,
    }


def selected_strategy_rows(summary_path: Path) -> list[dict[str, Any]]:
    summary = read_csv_or_empty(summary_path)
    if summary.empty or "selected_for_portfolio" not in summary.columns:
        return []
    selected_mask = summary["selected_for_portfolio"].map(
        lambda value: str(value).strip().lower() in {"1", "true", "yes"}
    )
    selected = summary[selected_mask].copy()
    return selected.to_dict(orient="records")


def run_experiment_fold(
    *,
    spec: ExperimentSpec,
    fold: Fold,
    spec_index: int,
    data_path: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_stem = f"{spec.name}_{fold.label}"
    summary_path = output_dir / "folds" / f"{run_stem}_summary.csv"
    bets_path = output_dir / "folds" / f"{run_stem}_bets.csv"
    log_path = output_dir / "logs" / f"{run_stem}.log"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    bets_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    seed = int(args.seed + spec_index * 1000 + fold.val_season)
    command = command_for_run(
        python_exe=args.python,
        data_path=data_path,
        spec=spec,
        fold=fold,
        args=args,
        summary_path=summary_path,
        bets_path=bets_path,
        seed=seed,
    )

    started_at = datetime.now()
    elapsed_seconds = 0.0
    status = "ok"
    return_code = 0

    if args.dry_run:
        status = "dry_run"
        log_path.write_text(" ".join(command) + "\n", encoding="utf-8")
    elif args.skip_existing and summary_path.exists() and bets_path.exists():
        status = "skipped_existing"
    else:
        started = time.perf_counter()
        process = subprocess.run(
            command,
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )
        elapsed_seconds = time.perf_counter() - started
        return_code = int(process.returncode)
        log_path.write_text(
            "COMMAND\n"
            + " ".join(command)
            + "\n\nSTDOUT\n"
            + process.stdout
            + "\n\nSTDERR\n"
            + process.stderr,
            encoding="utf-8",
        )
        if process.returncode != 0:
            status = "failed"

    metrics = summarize_bets(bets_path) if status in {"ok", "skipped_existing"} else {
        "test_bets": 0,
        "test_wins": 0,
        "test_profit": 0.0,
        "test_roi": None,
        "test_hit_rate": None,
        "test_avg_odds": None,
    }
    selected_rows = selected_strategy_rows(summary_path) if status in {"ok", "skipped_existing"} else []
    for row in selected_rows:
        row.update(
            {
                "experiment_name": spec.name,
                "fold": fold.label,
                "val_season": fold.val_season,
                "test_season": fold.test_season,
            }
        )

    registry_row = {
        "experiment_name": spec.name,
        "description": spec.description,
        "fold": fold.label,
        "val_season": fold.val_season,
        "test_season": fold.test_season,
        "status": status,
        "return_code": return_code,
        "started_at": started_at.isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "seed": seed,
        "trials": args.trials,
        "n_estimators": args.n_estimators,
        "selected_strategy_count": len(selected_rows),
        "summary_path": str(summary_path),
        "bets_path": str(bets_path),
        "log_path": str(log_path),
        **metrics,
    }
    return registry_row, selected_rows


def aggregate_leaderboard(
    registry: pd.DataFrame,
    *,
    expected_folds: int,
    min_total_test_bets: int,
    max_negative_folds: int,
) -> pd.DataFrame:
    rows = []
    for experiment_name, group in registry.groupby("experiment_name", sort=False):
        completed = group[group["status"].isin(["ok", "skipped_existing"])].copy()
        rois = completed["test_roi"].dropna()
        total_bets = int(completed["test_bets"].sum()) if not completed.empty else 0
        total_wins = int(completed["test_wins"].sum()) if not completed.empty else 0
        total_profit = float(completed["test_profit"].sum()) if not completed.empty else 0.0
        mean_roi = float(rois.mean()) if len(rois) else None
        median_roi = float(rois.median()) if len(rois) else None
        min_roi = float(rois.min()) if len(rois) else None
        max_roi = float(rois.max()) if len(rois) else None
        std_roi = float(rois.std(ddof=0)) if len(rois) > 1 else 0.0 if len(rois) == 1 else None
        risk_adjusted_roi = mean_roi - std_roi if mean_roi is not None and std_roi is not None else None
        negative_folds = int((completed["test_profit"] < 0).sum()) if not completed.empty else 0
        profitable_folds = int((completed["test_profit"] > 0).sum()) if not completed.empty else 0
        zero_bet_folds = int((completed["test_bets"] == 0).sum()) if not completed.empty else 0
        eligible = (
            len(completed) == expected_folds
            and total_bets >= min_total_test_bets
            and negative_folds <= max_negative_folds
        )
        rows.append(
            {
                "experiment_name": experiment_name,
                "eligible": bool(eligible),
                "completed_folds": int(len(completed)),
                "failed_folds": int(len(group) - len(completed)),
                "total_test_bets": total_bets,
                "total_test_wins": total_wins,
                "total_test_profit": total_profit,
                "pooled_test_roi": total_profit / total_bets if total_bets else None,
                "pooled_hit_rate": total_wins / total_bets if total_bets else None,
                "mean_fold_roi": mean_roi,
                "median_fold_roi": median_roi,
                "min_fold_roi": min_roi,
                "max_fold_roi": max_roi,
                "std_fold_roi": std_roi,
                "risk_adjusted_roi": risk_adjusted_roi,
                "profitable_folds": profitable_folds,
                "negative_folds": negative_folds,
                "zero_bet_folds": zero_bet_folds,
            }
        )

    leaderboard = pd.DataFrame(rows)
    if leaderboard.empty:
        return leaderboard

    sort_cols = [
        "eligible",
        "risk_adjusted_roi",
        "median_fold_roi",
        "pooled_test_roi",
        "total_test_profit",
        "total_test_bets",
    ]
    leaderboard = leaderboard.sort_values(sort_cols, ascending=[False, False, False, False, False, False])
    leaderboard.insert(0, "rank", range(1, len(leaderboard) + 1))
    return leaderboard.reset_index(drop=True)


def combine_best_bets(registry: pd.DataFrame, best_experiment: str, output_path: Path) -> int:
    frames = []
    best_runs = registry[
        (registry["experiment_name"] == best_experiment)
        & registry["status"].isin(["ok", "skipped_existing"])
    ]
    for row in best_runs.itertuples(index=False):
        bets = read_csv_or_empty(Path(row.bets_path))
        if bets.empty:
            continue
        meta = pd.DataFrame(
            {
                "experiment_name": best_experiment,
                "fold": row.fold,
                "val_season": row.val_season,
                "test_season": row.test_season,
            },
            index=bets.index,
        )
        frames.append(pd.concat([meta, bets], axis=1))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not frames:
        pd.DataFrame().to_csv(output_path, index=False)
        return 0

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(output_path, index=False)
    return int(len(combined))


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


def format_optional_float(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.4f}"


def write_report(
    *,
    output_path: Path,
    dataset_profile: dict[str, Any],
    specs: list[ExperimentSpec],
    folds: list[Fold],
    registry: pd.DataFrame,
    leaderboard: pd.DataFrame,
    best_bets_path: Path,
    args: argparse.Namespace,
) -> None:
    top_rows = leaderboard.head(10).to_dict(orient="records") if not leaderboard.empty else []
    final_2025_rows = registry[registry["test_season"] == 2025].copy()
    final_rows = final_2025_rows[
        [
            "experiment_name",
            "test_bets",
            "test_profit",
            "test_roi",
            "test_hit_rate",
            "selected_strategy_count",
            "status",
        ]
    ].to_dict(orient="records")

    recommendation = "No eligible experiment met the robustness filters."
    if not leaderboard.empty:
        best = leaderboard.iloc[0].to_dict()
        recommendation = (
            f"Rank 1 is {best['experiment_name']} with pooled ROI "
            f"{format_optional_float(best.get('pooled_test_roi'))}, {int(best.get('total_test_bets', 0))} "
            "out-of-sample bets, and risk-adjusted ROI "
            f"{format_optional_float(best.get('risk_adjusted_roi'))}."
        )
        if not bool(best.get("eligible")):
            recommendation += " It is not eligible under the configured robustness filters."

    lines = [
        "# Experimental protocol report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Dataset",
        "",
        f"- Rows with targets: {dataset_profile['rows']}",
        f"- Unique matches: {dataset_profile['matches']}",
        f"- Date range: {dataset_profile['min_date']} to {dataset_profile['max_date']}",
        f"- Seasons: {dataset_profile['min_season']} to {dataset_profile['max_season']}",
        f"- Season 2025 matches: {dataset_profile['season_match_counts'].get('2025', 0)}",
        "",
        "## Protocol",
        "",
        "- Each fold trains on seasons before the validation season.",
        "- The validation season selects strategy rules and portfolio composition.",
        "- The following season is held out as test and is not used for selection.",
        f"- Portfolio selection split: {args.portfolio_selection_split}",
        f"- Test fit scope: {args.test_fit_scope}",
        f"- Algorithmic features enabled: {args.include_algo_features}",
        f"- Closing market features enabled: {args.include_closing_market_features}",
        f"- Consensus market features enabled: {args.include_consensus_market_features}",
        f"- Trials per experiment/fold: {args.trials}",
        f"- Model estimators/iterations per fit: {args.n_estimators}",
        f"- Robustness filters: at least {args.min_total_test_bets} total bets and no more than {args.max_negative_folds} negative folds.",
        "",
        "## Folds",
        "",
        markdown_table([asdict(fold) for fold in folds], ["val_season", "test_season"]),
        "",
        "## Hypotheses",
        "",
        markdown_table(
            [asdict(spec) for spec in specs],
            ["name", "model_variants", "outcomes", "odds_ranges", "market_favorite_modes", "profile_filters"],
        ),
        "",
        "## Leaderboard",
        "",
        markdown_table(
            top_rows,
            [
                "rank",
                "experiment_name",
                "eligible",
                "total_test_bets",
                "total_test_profit",
                "pooled_test_roi",
                "median_fold_roi",
                "min_fold_roi",
                "risk_adjusted_roi",
                "negative_folds",
            ],
        ),
        "",
        "## Final full-season fold",
        "",
        "This is the fold where validation is season 2024 and test is season 2025.",
        "",
        markdown_table(final_rows, ["experiment_name", "test_bets", "test_profit", "test_roi", "test_hit_rate", "selected_strategy_count", "status"]),
        "",
        "## Recommendation",
        "",
        recommendation,
        "",
        "## Output files",
        "",
        f"- Registry: {output_path.with_name('experiment_registry.csv')}",
        f"- Leaderboard: {output_path.with_name('experiment_leaderboard.csv')}",
        f"- Selected strategies: {output_path.with_name('selected_strategies.csv')}",
        f"- Best experiment bets: {best_bets_path}",
        "",
        "Note: this is a research ranking, not betting advice. The raw model probabilities are not calibrated.",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    data_path = resolve_path(args.data)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df, dataset_profile = load_dataset_profile(data_path)
    folds = build_folds(df, args.start_val_season, args.end_val_season)
    specs = filter_experiment_specs(
        build_experiment_specs(args.profile),
        include_experiments=args.include_experiments,
        exclude_experiments=args.exclude_experiments,
    )

    print(
        {
            "profile": args.profile,
            "experiments": len(specs),
            "folds": [fold.label for fold in folds],
            "season_2025_matches": dataset_profile["season_match_counts"].get("2025", 0),
            "output_dir": str(output_dir),
        }
    )

    registry_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    for spec_index, spec in enumerate(specs):
        for fold in folds:
            print(f"running {spec.name} {fold.label}")
            registry_row, selected = run_experiment_fold(
                spec=spec,
                fold=fold,
                spec_index=spec_index,
                data_path=data_path,
                output_dir=output_dir,
                args=args,
            )
            registry_rows.append(registry_row)
            selected_rows.extend(selected)
            print(
                {
                    "status": registry_row["status"],
                    "bets": registry_row["test_bets"],
                    "profit": round(float(registry_row["test_profit"]), 4),
                    "roi": registry_row["test_roi"],
                    "log": registry_row["log_path"],
                }
            )
            if registry_row["status"] == "failed" and not args.continue_on_error:
                raise RuntimeError(f"{spec.name} {fold.label} failed; see {registry_row['log_path']}")

    registry = pd.DataFrame(registry_rows)
    selected = pd.DataFrame(selected_rows)
    leaderboard = aggregate_leaderboard(
        registry,
        expected_folds=len(folds),
        min_total_test_bets=args.min_total_test_bets,
        max_negative_folds=args.max_negative_folds,
    )

    registry_path = output_dir / "experiment_registry.csv"
    selected_path = output_dir / "selected_strategies.csv"
    leaderboard_path = output_dir / "experiment_leaderboard.csv"
    best_bets_path = output_dir / "best_strategy_bets.csv"
    report_path = output_dir / "experimental_protocol_report.md"
    json_path = output_dir / "experimental_protocol_report.json"

    registry.to_csv(registry_path, index=False)
    selected.to_csv(selected_path, index=False)
    leaderboard.to_csv(leaderboard_path, index=False)

    best_experiment = str(leaderboard.iloc[0]["experiment_name"]) if not leaderboard.empty else ""
    best_bets_count = combine_best_bets(registry, best_experiment, best_bets_path) if best_experiment else 0

    write_report(
        output_path=report_path,
        dataset_profile=dataset_profile,
        specs=specs,
        folds=folds,
        registry=registry,
        leaderboard=leaderboard,
        best_bets_path=best_bets_path,
        args=args,
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "dataset": dataset_profile,
        "folds": [asdict(fold) for fold in folds],
        "experiments": [asdict(spec) for spec in specs],
        "outputs": {
            "registry": str(registry_path),
            "selected_strategies": str(selected_path),
            "leaderboard": str(leaderboard_path),
            "best_strategy_bets": str(best_bets_path),
            "report": str(report_path),
        },
        "best_bets_count": best_bets_count,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        {
            "registry": str(registry_path),
            "leaderboard": str(leaderboard_path),
            "report": str(report_path),
            "best_strategy_bets": str(best_bets_path),
            "best_bets_count": best_bets_count,
        }
    )


if __name__ == "__main__":
    main()
