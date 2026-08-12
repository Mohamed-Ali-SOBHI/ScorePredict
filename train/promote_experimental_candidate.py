from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROTOCOL_DIR = SCRIPT_DIR / "output" / "experimental_protocol"


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote the best experimental protocol result into a research candidate manifest."
    )
    parser.add_argument("--protocol-dir", default=str(DEFAULT_PROTOCOL_DIR))
    parser.add_argument("--experiment-name", default="")
    parser.add_argument("--latest-fold-only", action="store_true", default=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-snippet", default="")
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def first_eligible_experiment(leaderboard: pd.DataFrame) -> str:
    if leaderboard.empty:
        raise ValueError("Leaderboard is empty")
    eligible = leaderboard[leaderboard["eligible"].astype(bool)].copy()
    if not eligible.empty:
        return str(eligible.sort_values("rank").iloc[0]["experiment_name"])
    return str(leaderboard.sort_values("rank").iloc[0]["experiment_name"])


def sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    if not cleaned:
        cleaned = "strategy"
    if cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned


def parse_params(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        return {str(key): float(val) for key, val in value.items()}
    parsed = ast.literal_eval(str(value))
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid params payload: {value!r}")
    return {str(key): float(val) for key, val in parsed.items()}


def strategy_record(row: pd.Series, index: int, *, n_estimators: int) -> dict[str, Any]:
    train_league = "" if str(row["train_league"]) == "ALL" else str(row["train_league"])
    profile_filter = str(row.get("profile_filter", "any"))
    base_name = (
        f"{row['bet_league']}_{row['outcome']}_{row['odds_min']:.2f}_{row['odds_max']:.2f}_"
        f"{row['market_favorite_mode']}_{index}"
    )
    if profile_filter != "any":
        base_name = f"{base_name}_{profile_filter}"
    return {
        "name": sanitize_identifier(base_name),
        "source_strategy_name": str(row["strategy_name"]),
        "model_variant": str(row.get("model_variant", "multiclass")),
        "train_league": train_league,
        "bet_league": str(row["bet_league"]),
        "outcome": str(row["outcome"]),
        "odds_min": float(row["odds_min"]),
        "odds_max": float(row["odds_max"]),
        "market_favorite_mode": str(row["market_favorite_mode"]),
        "profile_filter": profile_filter,
        "threshold": float(row["threshold"]),
        "edge_min": float(row["edge_min"]),
        "params": parse_params(row["params"]),
        "n_estimators": int(n_estimators),
        "validation": {
            "bets": int(row["val_bets"]),
            "roi": None if pd.isna(row["val_roi"]) else float(row["val_roi"]),
            "profit": None if "val_profit" not in row or pd.isna(row["val_profit"]) else float(row["val_profit"]),
        },
        "latest_test": {
            "bets": int(row["test_bets"]),
            "roi": None if pd.isna(row["test_roi"]) else float(row["test_roi"]),
            "profit": None if pd.isna(row["test_profit"]) else float(row["test_profit"]),
        },
    }


def build_candidate(protocol_dir: Path, requested_experiment: str) -> dict[str, Any]:
    leaderboard = read_csv(protocol_dir / "experiment_leaderboard.csv")
    registry = read_csv(protocol_dir / "experiment_registry.csv")
    selected = read_csv(protocol_dir / "selected_strategies.csv")

    experiment_name = requested_experiment or first_eligible_experiment(leaderboard)
    leaderboard_row = leaderboard[leaderboard["experiment_name"] == experiment_name]
    if leaderboard_row.empty:
        raise ValueError(f"Experiment not found in leaderboard: {experiment_name}")

    experiment_selected = selected[selected["experiment_name"] == experiment_name].copy()
    if experiment_selected.empty:
        raise ValueError(f"No selected strategies found for experiment: {experiment_name}")

    latest_test_season = int(experiment_selected["test_season"].max())
    latest_fold_rows = experiment_selected[experiment_selected["test_season"] == latest_test_season].copy()
    latest_fold_rows = latest_fold_rows.sort_values(["test_profit", "test_roi", "test_bets"], ascending=False)
    latest_val_season = int(latest_fold_rows["val_season"].iloc[0])
    latest_fold = str(latest_fold_rows["fold"].iloc[0])

    final_registry = registry[
        (registry["experiment_name"] == experiment_name)
        & (registry["test_season"] == latest_test_season)
    ]
    final_fold_metrics = final_registry.iloc[0].to_dict() if not final_registry.empty else {}
    rank_row = leaderboard_row.iloc[0].to_dict()

    n_estimators = int(final_fold_metrics.get("n_estimators", 500))
    strategies = [
        strategy_record(row, index, n_estimators=n_estimators)
        for index, (_, row) in enumerate(latest_fold_rows.iterrows(), start=1)
    ]

    conservative_train_max_season = latest_val_season - 1
    refit_train_max_season = latest_test_season
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_protocol_dir": str(protocol_dir),
        "experiment_name": experiment_name,
        "deployment_status": "research_candidate_not_live_default",
        "selection_policy": (
            "Best eligible experiment by protocol leaderboard; deployable rules are taken "
            "from the latest completed validation/test fold."
        ),
        "latest_fold": {
            "fold": latest_fold,
            "val_season": latest_val_season,
            "test_season": latest_test_season,
            "conservative_train_max_season": conservative_train_max_season,
            "refit_train_max_season": refit_train_max_season,
            "n_estimators": n_estimators,
        },
        "leaderboard_metrics": {
            "rank": int(rank_row["rank"]),
            "eligible": bool(rank_row["eligible"]),
            "completed_folds": int(rank_row["completed_folds"]),
            "total_test_bets": int(rank_row["total_test_bets"]),
            "total_test_profit": float(rank_row["total_test_profit"]),
            "pooled_test_roi": float(rank_row["pooled_test_roi"]),
            "median_fold_roi": float(rank_row["median_fold_roi"]),
            "min_fold_roi": float(rank_row["min_fold_roi"]),
            "risk_adjusted_roi": float(rank_row["risk_adjusted_roi"]),
            "negative_folds": int(rank_row["negative_folds"]),
        },
        "latest_fold_metrics": {
            "test_bets": int(final_fold_metrics.get("test_bets", 0)),
            "test_profit": float(final_fold_metrics.get("test_profit", 0.0)),
            "test_roi": None
            if pd.isna(final_fold_metrics.get("test_roi"))
            else float(final_fold_metrics.get("test_roi")),
            "test_hit_rate": None
            if pd.isna(final_fold_metrics.get("test_hit_rate"))
            else float(final_fold_metrics.get("test_hit_rate")),
            "selected_strategy_count": int(final_fold_metrics.get("selected_strategy_count", len(strategies))),
        },
        "risk_notes": [
            "This candidate is not betting advice.",
            "The protocol result is encouraging but not statistically decisive.",
            "Use conservative_train_max_season to reproduce the validated fold behavior.",
            "Use refit_train_max_season only as a deliberate production refit, not as equivalent evidence.",
        ],
        "strategies": strategies,
    }


def format_percent(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value) * 100:.2f}%"


def write_markdown(candidate: dict[str, Any], output_path: Path) -> None:
    latest = candidate["latest_fold"]
    metrics = candidate["leaderboard_metrics"]
    final_metrics = candidate["latest_fold_metrics"]
    rows = []
    for strategy in candidate["strategies"]:
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{strategy['name']}`",
                    f"`{strategy['model_variant']}`",
                    f"`{strategy['train_league'] or 'ALL'}`",
                    f"`{strategy['bet_league']}`",
                    f"`{strategy['outcome']}`",
                    f"`[{strategy['odds_min']:.2f},{strategy['odds_max']:.2f})`",
                    f"`{strategy['market_favorite_mode']}`",
                    f"`{strategy['profile_filter']}`",
                    f"`{strategy['threshold']:.2f}`",
                    f"`{strategy['edge_min']:.2f}`",
                    str(strategy["latest_test"]["bets"]),
                    format_percent(strategy["latest_test"]["roi"]),
                ]
            )
            + " |"
        )

    text = f"""# Recommended Experimental Candidate

Generated: `{candidate['generated_at']}`

## Decision

Best current research candidate: `{candidate['experiment_name']}`

Status: `{candidate['deployment_status']}`

This is the best eligible experiment in the protocol leaderboard. It is not automatically enabled as the live default.

## Evidence

- Completed folds: `{metrics['completed_folds']}`
- Total out-of-sample bets: `{metrics['total_test_bets']}`
- Total out-of-sample profit: `{metrics['total_test_profit']:.2f}` units
- Pooled ROI: `{format_percent(metrics['pooled_test_roi'])}`
- Median fold ROI: `{format_percent(metrics['median_fold_roi'])}`
- Worst fold ROI: `{format_percent(metrics['min_fold_roi'])}`
- Negative folds: `{metrics['negative_folds']}`
- Risk-adjusted ROI: `{format_percent(metrics['risk_adjusted_roi'])}`

Latest fully tested fold:
- Fold: `{latest['fold']}`
- Validation season: `{latest['val_season']}`
- Test season: `{latest['test_season']}`
- Test bets: `{final_metrics['test_bets']}`
- Test profit: `{final_metrics['test_profit']:.2f}` units
- Test ROI: `{format_percent(final_metrics['test_roi'])}`

## Train Season Policy

- Conservative reproduction: `TrainMaxSeason {latest['conservative_train_max_season']}`
- Deliberate production refit: `TrainMaxSeason {latest['refit_train_max_season']}`
- Model estimators per strategy: `{latest['n_estimators']}`

The conservative setting reproduces the validation/test evidence. The refit setting can be useful for future predictions, but it is a new production choice and should be tracked separately.

## Frozen Strategy Rules

| Name | Model | Train | League | Outcome | Odds | Favorite mode | Profile | EV threshold | Edge min | Latest test bets | Latest test ROI |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## Risk Notes

{chr(10).join(f"- {item}" for item in candidate['risk_notes'])}
"""
    output_path.write_text(text, encoding="utf-8")


def render_params(params: dict[str, float], indent: str = "            ") -> str:
    lines = ["{"]
    for key, value in params.items():
        if float(value).is_integer():
            rendered = str(int(value))
        else:
            rendered = repr(float(value))
        lines.append(f"{indent}\"{key}\": {rendered},")
    lines.append("        }")
    return "\n".join(lines)


def write_presets_snippet(candidate: dict[str, Any], output_path: Path) -> None:
    constant_name = f"EXPERIMENTAL_{sanitize_identifier(candidate['experiment_name']).upper()}_{candidate['latest_fold']['test_season']}"
    blocks = []
    for strategy in candidate["strategies"]:
        blocks.append(
            "    FrozenStrategy(\n"
            f"        name=\"{strategy['name']}\",\n"
            f"        train_league=\"{strategy['train_league']}\",\n"
            f"        bet_league=\"{strategy['bet_league']}\",\n"
            f"        outcome=\"{strategy['outcome']}\",\n"
            f"        odds_min={strategy['odds_min']:.1f},\n"
            f"        odds_max={strategy['odds_max']:.1f},\n"
            f"        market_favorite_mode=\"{strategy['market_favorite_mode']}\",\n"
            f"        threshold={strategy['threshold']:.2f},\n"
            f"        edge_min={strategy['edge_min']:.2f},\n"
            f"        params={render_params(strategy['params'])},\n"
            f"        model_variant=\"{strategy['model_variant']}\",\n"
            f"        n_estimators={strategy['n_estimators']},\n"
            f"        profile_filter=\"{strategy['profile_filter']}\",\n"
            "    )"
        )

    text = (
        "from inference.portfolio_presets import FrozenStrategy\n\n"
        f"# Research candidate generated from {candidate['source_protocol_dir']}\n"
        f"# Conservative TrainMaxSeason: {candidate['latest_fold']['conservative_train_max_season']}\n"
        f"# Production refit TrainMaxSeason: {candidate['latest_fold']['refit_train_max_season']}\n"
        f"{constant_name} = [\n"
        + ",\n".join(blocks)
        + "\n]\n"
    )
    output_path.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    protocol_dir = resolve_path(args.protocol_dir)
    candidate = build_candidate(protocol_dir, args.experiment_name)

    output_json = resolve_path(args.output_json) if args.output_json else protocol_dir / "recommended_strategy_candidate.json"
    output_md = resolve_path(args.output_md) if args.output_md else protocol_dir / "recommended_strategy_candidate.md"
    output_snippet = (
        resolve_path(args.output_snippet)
        if args.output_snippet
        else protocol_dir / "recommended_strategy_candidate_snippet.py"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_snippet.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    write_markdown(candidate, output_md)
    write_presets_snippet(candidate, output_snippet)

    print(
        {
            "experiment_name": candidate["experiment_name"],
            "strategies": len(candidate["strategies"]),
            "conservative_train_max_season": candidate["latest_fold"]["conservative_train_max_season"],
            "refit_train_max_season": candidate["latest_fold"]["refit_train_max_season"],
            "output_json": str(output_json),
            "output_md": str(output_md),
            "output_snippet": str(output_snippet),
        }
    )


if __name__ == "__main__":
    main()
