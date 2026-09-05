from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path


FROZEN_REFERENCE_FREEZE_DATE = "2026-03-12"
FROZEN_REFERENCE_TRAIN_MAX_SEASON = 2023
PRODUCTION_REFIT_TRAIN_MAX_SEASON = 2024
LEGACY_PRODUCTION_PORTFOLIO_NAME = "production_draw_consensus_nonfavorite_2026_08_12"
PRODUCTION_PORTFOLIO_NAME = "production_draw_pooled_unweighted_2026_09_05"
PRODUCTION_FREEZE_DATE = "2026-09-05"
PRODUCTION_RELEASE_PATH = Path(__file__).resolve().parent / "releases" / "draw_pooled_2026_09_05"


@dataclass(frozen=True)
class FrozenStrategy:
    name: str
    train_league: str
    bet_league: str
    outcome: str
    odds_min: float
    odds_max: float
    market_favorite_mode: str
    threshold: float
    edge_min: float
    params: dict[str, float]
    model_variant: str = "multiclass"
    n_estimators: int = 500
    profile_filter: str = "any"
    training_weight_mode: str = "balanced"


EXPLORATORY_MULTI_STRATEGY_PORTFOLIO_2025 = [
    FrozenStrategy(
        name="serie_a_draw_long_nonfavorite",
        train_league="Serie_A",
        bet_league="Serie_A",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.10,
        edge_min=0.10,
        params={
            "max_depth": 3,
            "min_child_weight": 8.291506340399406,
            "subsample": 0.9800304656711365,
            "colsample_bytree": 0.6789008020969248,
            "gamma": 3.6992337172481085,
            "reg_lambda": 0.6864461853969224,
            "learning_rate": 0.0510878727512436,
        },
    ),
    FrozenStrategy(
        name="epl_draw_long_nonfavorite",
        train_league="EPL",
        bet_league="EPL",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.30,
        edge_min=0.0,
        params={
            "max_depth": 7,
            "min_child_weight": 2.2598308088957078,
            "subsample": 0.8507813328057123,
            "colsample_bytree": 0.7619932927644096,
            "gamma": 2.2609444259247553,
            "reg_lambda": 6.237491430620192,
            "learning_rate": 0.0562566908000384,
        },
    ),
    FrozenStrategy(
        name="bundesliga_draw_mid_nonfavorite",
        train_league="",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=2.2,
        odds_max=4.0,
        market_favorite_mode="nonfavorite",
        threshold=0.45,
        edge_min=0.0,
        params={
            "max_depth": 3,
            "min_child_weight": 5.827662837272576,
            "subsample": 0.9363690639601221,
            "colsample_bytree": 0.8638156130767138,
            "gamma": 0.3767093915505981,
            "reg_lambda": 7.817167637275669,
            "learning_rate": 0.06447408062937295,
        },
    ),
    FrozenStrategy(
        name="ligue1_draw_wide_nonfavorite",
        train_league="",
        bet_league="Ligue_1",
        outcome="draw",
        odds_min=2.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.70,
        edge_min=0.10,
        params={
            "max_depth": 5,
            "min_child_weight": 5.0750567663835575,
            "subsample": 0.7613001150741135,
            "colsample_bytree": 0.6352621115879286,
            "gamma": 0.5196860213418866,
            "reg_lambda": 4.067786946694503,
            "learning_rate": 0.029749107688307467,
        },
    ),
]

VALIDATION_MULTI_STRATEGY_PORTFOLIO_2024 = [
    FrozenStrategy(
        name="bundesliga_local_draw_long_nonfavorite",
        train_league="Bundesliga",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.50,
        edge_min=0.10,
        params={
            "max_depth": 5,
            "min_child_weight": 5.0750567663835575,
            "subsample": 0.7613001150741135,
            "colsample_bytree": 0.6352621115879286,
            "gamma": 0.5196860213418866,
            "reg_lambda": 4.067786946694503,
            "learning_rate": 0.029749107688307467,
        },
    ),
    FrozenStrategy(
        name="laliga_draw_mid_nonfavorite",
        train_league="",
        bet_league="La_liga",
        outcome="draw",
        odds_min=2.2,
        odds_max=4.0,
        market_favorite_mode="nonfavorite",
        threshold=0.45,
        edge_min=0.00,
        params={
            "max_depth": 3,
            "min_child_weight": 5.827662837272576,
            "subsample": 0.9363690639601221,
            "colsample_bytree": 0.8638156130767138,
            "gamma": 0.3767093915505981,
            "reg_lambda": 7.817167637275669,
            "learning_rate": 0.06447408062937295,
        },
    ),
    FrozenStrategy(
        name="epl_draw_long_nonfavorite",
        train_league="",
        bet_league="EPL",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.10,
        edge_min=0.06,
        params={
            "max_depth": 3,
            "min_child_weight": 5.827662837272576,
            "subsample": 0.9363690639601221,
            "colsample_bytree": 0.8638156130767138,
            "gamma": 0.3767093915505981,
            "reg_lambda": 7.817167637275669,
            "learning_rate": 0.06447408062937295,
        },
    ),
    FrozenStrategy(
        name="bundesliga_draw_wide_nonfavorite",
        train_league="",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=2.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.55,
        edge_min=0.08,
        params={
            "max_depth": 7,
            "min_child_weight": 9.646707358046491,
            "subsample": 0.6076511347039957,
            "colsample_bytree": 0.7526736720530052,
            "gamma": 1.483192096930325,
            "reg_lambda": 7.450737416364514,
            "learning_rate": 0.05685123280524319,
        },
    ),
]


EXPERIMENTAL_DRAW_CONSENSUS_NONFAVORITE_2025 = [
    FrozenStrategy(
        name="bundesliga_draw_2_20_4_00_nonfavorite_1",
        train_league="Bundesliga",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=2.2,
        odds_max=4.0,
        market_favorite_mode="nonfavorite",
        threshold=0.55,
        edge_min=0.00,
        params={
            "max_depth": 7,
            "min_child_weight": 3.396174921502335,
            "subsample": 0.6382917916170425,
            "colsample_bytree": 0.7197871718473745,
            "gamma": 0.7017444608369803,
            "reg_lambda": 2.0679555186082506,
            "learning_rate": 0.041917293325307955,
        },
        model_variant="draw_consensus",
        n_estimators=120,
    ),
    FrozenStrategy(
        name="serie_a_draw_4_00_10_00_nonfavorite_2",
        train_league="Serie_A",
        bet_league="Serie_A",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.50,
        edge_min=0.00,
        params={
            "max_depth": 3,
            "min_child_weight": 2.949348806153654,
            "subsample": 0.9308308528665842,
            "colsample_bytree": 0.5808808750509551,
            "gamma": 0.061886730191146544,
            "reg_lambda": 1.6286497938057933,
            "learning_rate": 0.054065608178171895,
        },
        model_variant="draw_consensus",
        n_estimators=120,
    ),
    FrozenStrategy(
        name="epl_draw_2_00_10_00_nonfavorite_3",
        train_league="",
        bet_league="EPL",
        outcome="draw",
        odds_min=2.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.50,
        edge_min=0.10,
        params={
            "max_depth": 6,
            "min_child_weight": 11.136045022255074,
            "subsample": 0.7996648045663242,
            "colsample_bytree": 0.7038178095553498,
            "gamma": 1.0760879976053435,
            "reg_lambda": 1.9467082637463466,
            "learning_rate": 0.021492450278278133,
        },
        model_variant="draw_consensus",
        n_estimators=120,
    ),
    FrozenStrategy(
        name="bundesliga_draw_4_00_10_00_nonfavorite_4",
        train_league="Bundesliga",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.40,
        edge_min=0.08,
        params={
            "max_depth": 7,
            "min_child_weight": 3.396174921502335,
            "subsample": 0.6382917916170425,
            "colsample_bytree": 0.7197871718473745,
            "gamma": 0.7017444608369803,
            "reg_lambda": 2.0679555186082506,
            "learning_rate": 0.041917293325307955,
        },
        model_variant="draw_consensus",
        n_estimators=120,
    ),
]


EXPERIMENTAL_DRAW_CONSENSUS_PLUS_ANTI_OVERCONFIDENCE_2025 = [
    *EXPERIMENTAL_DRAW_CONSENSUS_NONFAVORITE_2025,
    FrozenStrategy(
        name="epl_draw_4_00_10_00_anti_overconfidence_1",
        train_league="EPL",
        bet_league="EPL",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.50,
        edge_min=0.08,
        params={
            "max_depth": 5,
            "min_child_weight": 8.600681336464175,
            "subsample": 0.9072444605008649,
            "colsample_bytree": 0.897528988704875,
            "gamma": 1.0441855605362358,
            "reg_lambda": 7.298838378148277,
            "learning_rate": 0.04161760188105333,
        },
        model_variant="draw_consensus",
        n_estimators=120,
        profile_filter="anti_overconfidence",
    ),
    FrozenStrategy(
        name="serie_a_draw_4_00_10_00_anti_overconfidence_2",
        train_league="Serie_A",
        bet_league="Serie_A",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.45,
        edge_min=0.08,
        params={
            "max_depth": 5,
            "min_child_weight": 6.934092792912184,
            "subsample": 0.7556025953393389,
            "colsample_bytree": 0.8723319596952671,
            "gamma": 1.8522608720337312,
            "reg_lambda": 6.829144772653557,
            "learning_rate": 0.02823492506374921,
        },
        model_variant="draw_consensus",
        n_estimators=120,
        profile_filter="anti_overconfidence",
    ),
    FrozenStrategy(
        name="serie_a_draw_2_00_10_00_anti_overconfidence_3",
        train_league="",
        bet_league="Serie_A",
        outcome="draw",
        odds_min=2.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.50,
        edge_min=0.00,
        params={
            "max_depth": 3,
            "min_child_weight": 5.733274486019898,
            "subsample": 0.9150871379178315,
            "colsample_bytree": 0.6438277099264523,
            "gamma": 3.9710572387136986,
            "reg_lambda": 4.4984435938760985,
            "learning_rate": 0.04346759757592941,
        },
        model_variant="draw_consensus",
        n_estimators=120,
        profile_filter="anti_overconfidence",
    ),
    FrozenStrategy(
        name="bundesliga_draw_4_00_10_00_anti_overconfidence_4",
        train_league="",
        bet_league="Bundesliga",
        outcome="draw",
        odds_min=4.0,
        odds_max=10.0,
        market_favorite_mode="nonfavorite",
        threshold=0.55,
        edge_min=0.10,
        params={
            "max_depth": 3,
            "min_child_weight": 5.733274486019898,
            "subsample": 0.9150871379178315,
            "colsample_bytree": 0.6438277099264523,
            "gamma": 3.9710572387136986,
            "reg_lambda": 4.4984435938760985,
            "learning_rate": 0.04346759757592941,
        },
        model_variant="draw_consensus",
        n_estimators=120,
        profile_filter="anti_overconfidence",
    ),
]


PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026 = tuple(EXPERIMENTAL_DRAW_CONSENSUS_NONFAVORITE_2025)


SHADOW_UNWEIGHTED_PORTFOLIO_NAME = "shadow_draw_consensus_unweighted_2026_09_01"
SHADOW_RECENCY_PORTFOLIO_NAME = "shadow_draw_consensus_recency_2026_09_01"

_PRODUCTION_BY_NAME = {
    strategy.name: strategy for strategy in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
}

SHADOW_DRAW_CONSENSUS_UNWEIGHTED_2026 = (
    replace(
        _PRODUCTION_BY_NAME["bundesliga_draw_2_20_4_00_nonfavorite_1"],
        name="shadow_unweighted_bundesliga_draw_2_20_4_00_1",
        threshold=0.05,
        edge_min=0.00,
        training_weight_mode="unweighted",
    ),
    replace(
        _PRODUCTION_BY_NAME["epl_draw_2_00_10_00_nonfavorite_3"],
        name="shadow_unweighted_epl_draw_2_00_10_00_2",
        threshold=0.05,
        edge_min=0.04,
        training_weight_mode="unweighted",
    ),
    replace(
        _PRODUCTION_BY_NAME["bundesliga_draw_4_00_10_00_nonfavorite_4"],
        name="shadow_unweighted_bundesliga_draw_4_00_10_00_3",
        threshold=0.05,
        edge_min=0.04,
        training_weight_mode="unweighted",
    ),
)

SHADOW_DRAW_CONSENSUS_RECENCY_2026 = (
    replace(
        _PRODUCTION_BY_NAME["bundesliga_draw_2_20_4_00_nonfavorite_1"],
        name="shadow_recency_bundesliga_draw_2_20_4_00_1",
        threshold=0.20,
        edge_min=0.00,
        training_weight_mode="recency_decay_0_80",
    ),
    replace(
        _PRODUCTION_BY_NAME["serie_a_draw_4_00_10_00_nonfavorite_2"],
        name="shadow_recency_serie_a_draw_4_00_10_00_2",
        threshold=0.40,
        edge_min=0.06,
        training_weight_mode="recency_decay_0_80",
    ),
    replace(
        _PRODUCTION_BY_NAME["epl_draw_2_00_10_00_nonfavorite_3"],
        name="shadow_recency_epl_draw_2_00_10_00_3",
        threshold=0.50,
        edge_min=0.08,
        training_weight_mode="recency_decay_0_80",
    ),
    replace(
        _PRODUCTION_BY_NAME["bundesliga_draw_4_00_10_00_nonfavorite_4"],
        name="shadow_recency_bundesliga_draw_4_00_10_00_4",
        threshold=0.05,
        edge_min=0.10,
        training_weight_mode="recency_decay_0_80",
    ),
)

SHADOW_PORTFOLIO_NAMES = (
    SHADOW_UNWEIGHTED_PORTFOLIO_NAME,
    SHADOW_RECENCY_PORTFOLIO_NAME,
)


DEFAULT_PORTFOLIO_NAME = PRODUCTION_PORTFOLIO_NAME
POOLED_RELEASE_MANIFEST = json.loads((PRODUCTION_RELEASE_PATH / "manifest.json").read_text(encoding="utf-8"))
if POOLED_RELEASE_MANIFEST["portfolio_name"] != PRODUCTION_PORTFOLIO_NAME:
    raise ValueError("Production release identity does not match the selected portfolio")
PRODUCTION_POOLED_STRATEGIES = tuple(FrozenStrategy(**entry["strategy"]) for entry in POOLED_RELEASE_MANIFEST["entries"])
PORTFOLIO_PRESETS = {
    "validation_multi_strategy_portfolio_2024": VALIDATION_MULTI_STRATEGY_PORTFOLIO_2024,
    "exploratory_multi_strategy_portfolio_2025": EXPLORATORY_MULTI_STRATEGY_PORTFOLIO_2025,
    "experimental_draw_consensus_nonfavorite_2025": EXPERIMENTAL_DRAW_CONSENSUS_NONFAVORITE_2025,
    "experimental_draw_consensus_plus_anti_overconfidence_2025": (
        EXPERIMENTAL_DRAW_CONSENSUS_PLUS_ANTI_OVERCONFIDENCE_2025
    ),
    LEGACY_PRODUCTION_PORTFOLIO_NAME: PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026,
    PRODUCTION_PORTFOLIO_NAME: PRODUCTION_POOLED_STRATEGIES,
    SHADOW_UNWEIGHTED_PORTFOLIO_NAME: SHADOW_DRAW_CONSENSUS_UNWEIGHTED_2026,
    SHADOW_RECENCY_PORTFOLIO_NAME: SHADOW_DRAW_CONSENSUS_RECENCY_2026,
}
