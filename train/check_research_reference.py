"""Compare the research implementation with the preceding evaluator on identical data."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import train.evaluate_model_challengers as original
from train.research_challengers_v2 import file_hash, save_json
from train.research_all_outcomes_v2 import load_frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-threads", action="store_true")
    parser.add_argument("--folder", default="train/output/research_v2_2026_09_05")
    args = parser.parse_args()
    folder = ROOT / args.folder
    dataset = pd.read_csv(ROOT / "train/dataset_home.csv", parse_dates=["date"])
    dataset = dataset[dataset.target.notna()].copy()
    dataset["target"] = dataset.target.astype(int)
    original_multi, original_binary = original.build_xgb_model, original.build_draw_binary_xgb_model
    if not args.native_threads:
        original.build_xgb_model = lambda **kwargs: original_multi(**kwargs).set_params(n_jobs=2)
        original.build_draw_binary_xgb_model = lambda **kwargs: original_binary(**kwargs).set_params(n_jobs=2)
    configurations, mappings = original.model_configurations()
    checks = {}
    with (nullcontext() if args.native_threads else threadpool_limits(limits=2)):
        for variant in (("unweighted",) if args.native_threads else ("current", "unweighted")):
            frames = []
            for model_id, strategy in configurations:
                frame, _ = original.fit_predict_fixed_holdout(dataset, strategy, variant,
                    validation_season=2024, test_season=2025)
                frame["model_id"] = model_id
                frames.append(frame)
            all_rows = pd.concat(frames, ignore_index=True)
            current = load_frame(folder, variant, 2025)
            comparison = all_rows.merge(current, on="match_id", suffixes=("_old", "_new"), validate="one_to_one")
            probabilities = ["p_away", "p_draw", "p_home", "p_binary_draw"]
            differences = {p: float(np.abs(comparison[p+"_old"] - comparison[p+"_new"]).max()) for p in probabilities}
            checks[variant] = {
                "max_probability_difference": differences,
                "original_evaluator_retuned_filters": original.tune_filters_on_validation(all_rows, mappings, variant,
                    validation_season=2024, test_season=2025),
                "original_evaluator_fixed_rules": original.betting_metrics(
                    original.select_portfolio_bets(all_rows[all_rows.season == 2025], mappings, variant)),
            }
            print(variant, differences, checks[variant]["original_evaluator_retuned_filters"]["test"], flush=True)
    prior = json.loads((ROOT / "train/output/production_final_four_benchmark.json").read_text(encoding="utf-8"))
    save_json(folder / ("reference_native_threads.json" if args.native_threads else "reference_reproduction_check.json"), {
        "original_native_thread_configuration": args.native_threads,
        "source_dataset_sha256_today": file_hash(ROOT / "train/dataset_home.csv"),
        "prior_benchmark_reproducibility": prior["reproducibility"], "checks": checks})


if __name__ == "__main__":
    main()
