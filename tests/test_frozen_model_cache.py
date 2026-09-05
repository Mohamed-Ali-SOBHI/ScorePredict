from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from inference.portfolio_presets import FrozenStrategy
from inference.upcoming_portfolio_strategy import (
    ModelBundle,
    load_or_train_frozen_models,
    make_strategy_sample_weight,
)


class FrozenModelCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = pd.DataFrame({"season": [2025], "target": [1]})
        self.strategy = FrozenStrategy(
            name="cache_test",
            train_league="",
            bet_league="EPL",
            outcome="draw",
            odds_min=2.0,
            odds_max=5.0,
            market_favorite_mode="nonfavorite",
            threshold=0.1,
            edge_min=0.1,
            params={},
        )
        self.bundle = ModelBundle(
            model_variant="multiclass",
            train_league="",
            train_max_season=2025,
            feature_cols=["example"],
            model="serialized-test-model",
        )

    def test_second_call_loads_the_frozen_bundle_without_training(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.pickle"
            with (
                patch(
                    "inference.upcoming_portfolio_strategy._model_cache_fingerprint",
                    return_value="stable-fingerprint",
                ),
                patch(
                    "inference.upcoming_portfolio_strategy.train_frozen_models",
                    return_value={self.strategy.name: self.bundle},
                ) as train_models,
            ):
                first, first_source = load_or_train_frozen_models(
                    self.dataset,
                    [self.strategy],
                    train_max_season=2025,
                    cache_path=cache_path,
                )
                second, second_source = load_or_train_frozen_models(
                    self.dataset,
                    [self.strategy],
                    train_max_season=2025,
                    cache_path=cache_path,
                )

            self.assertEqual(train_models.call_count, 1)
            self.assertEqual(first_source, "trained")
            self.assertEqual(second_source, "cache")
            self.assertEqual(first[self.strategy.name].model, "serialized-test-model")
            self.assertEqual(second[self.strategy.name].model, "serialized-test-model")

    def test_changed_training_fingerprint_forces_a_new_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.pickle"
            with (
                patch(
                    "inference.upcoming_portfolio_strategy._model_cache_fingerprint",
                    side_effect=["first-fingerprint", "second-fingerprint"],
                ),
                patch(
                    "inference.upcoming_portfolio_strategy.train_frozen_models",
                    return_value={self.strategy.name: self.bundle},
                ) as train_models,
            ):
                load_or_train_frozen_models(
                    self.dataset,
                    [self.strategy],
                    train_max_season=2025,
                    cache_path=cache_path,
                )
                _, source = load_or_train_frozen_models(
                    self.dataset,
                    [self.strategy],
                    train_max_season=2025,
                    cache_path=cache_path,
                )

            self.assertEqual(train_models.call_count, 2)
            self.assertEqual(source, "trained")

    def test_unweighted_shadow_does_not_pass_sample_weights(self) -> None:
        strategy = FrozenStrategy(
            **{
                **self.strategy.__dict__,
                "training_weight_mode": "unweighted",
            }
        )
        train = pd.DataFrame({"season": [2024, 2025], "target": [0, 1]})
        weights = make_strategy_sample_weight(
            train,
            train["target"],
            strategy,
            train_max_season=2025,
        )
        self.assertIsNone(weights)

    def test_recency_shadow_gives_more_weight_to_recent_rows(self) -> None:
        strategy = FrozenStrategy(
            **{
                **self.strategy.__dict__,
                "training_weight_mode": "recency_decay_0_80",
            }
        )
        train = pd.DataFrame({"season": [2023, 2025], "target": [1, 1]})
        weights = make_strategy_sample_weight(
            train,
            train["target"],
            strategy,
            train_max_season=2025,
        )
        self.assertIsNotNone(weights)
        self.assertGreater(float(weights.iloc[1]), float(weights.iloc[0]))


if __name__ == "__main__":
    unittest.main()
