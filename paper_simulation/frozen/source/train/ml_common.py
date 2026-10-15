from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, log_loss


OUTCOME_LABELS = ["L", "D", "W"]
DRAW_TARGET = 1


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_feature_cols(
    df: pd.DataFrame,
    *,
    include_draw_features: bool = False,
    include_algo_features: bool = False,
    include_closing_market_features: bool = False,
    include_consensus_market_features: bool = False,
) -> list[str]:
    drop_cols = {
        "match_id",
        "date",
        "league",
        "season",
        "team_id",
        "team_name",
        "opponent_id",
        "opponent_name",
        "away_team_id",
        "away_team_name",
        "result",
        "target",
    }

    candidate_cols = [c for c in df.columns if c not in drop_cols]
    numeric_cols = [c for c in candidate_cols if pd.api.types.is_numeric_dtype(df[c])]

    keep_prefixes = [
        "xG_advantage_",
        "defensive_advantage_",
        "deep_advantage_",
        "ppda_advantage_",
        "market_",
    ]
    if include_algo_features:
        keep_prefixes.append("algo_")
    if include_draw_features:
        keep_prefixes.extend(
            [
                "draw_abs_",
                "draw_market_",
                "draw_combined_draw_rate_",
                "draw_draw_rate_gap_",
                "draw_total_",
                "draw_elo_parity",
            ]
        )
    keep_exact = {
        "elo_rating_gap",
        "elo_win_probability",
        "rest_days_diff",
        "rest_days_ratio",
        "relative_form_5",
        "relative_form_10",
        "relative_form_5_carry",
        "relative_form_10_carry",
        "xG_efficiency_gap_5",
        "xG_trend_gap",
        "defensive_trend_gap",
        "prev_season_points_per_game_gap",
        "prev_season_xG_gap",
        "prev_season_defensive_gap",
        "season_points_per_game_gap",
    }
    def is_allowed_feature(column: str) -> bool:
        if not (column in keep_exact or any(column.startswith(prefix) for prefix in keep_prefixes)):
            return False
        if not include_closing_market_features and (
            column.endswith("_close")
            or "_close_" in column
            or "_move_close_minus_open" in column
        ):
            return False
        if not include_consensus_market_features and "_consensus_" in column:
            return False
        return True

    return [c for c in numeric_cols if is_allowed_feature(c)]


def time_split_grouped(
    df: pd.DataFrame,
    test_frac: float,
    group_col: str = "match_id",
    date_col: str = "date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values(date_col).reset_index(drop=True)

    group_dates = df.groupby(group_col, sort=False)[date_col].min().sort_values()
    group_ids = group_dates.index.to_numpy()

    split = int(len(group_ids) * (1.0 - test_frac))
    train_ids = set(group_ids[:split])
    test_ids = set(group_ids[split:])

    train_df = df[df[group_col].isin(train_ids)].copy()
    test_df = df[df[group_col].isin(test_ids)].copy()
    return train_df, test_df


def split_grouped_threeway(
    df: pd.DataFrame,
    group_col: str = "match_id",
    date_col: str = "date",
    train_frac: float = 0.7,
    val_frac: float = 0.1,
    test_frac: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not np.isclose(train_frac + val_frac + test_frac, 1.0):
        raise ValueError("train_frac + val_frac + test_frac must equal 1.0")

    df = df.sort_values(date_col).reset_index(drop=True)

    group_dates = df.groupby(group_col, sort=False)[date_col].min().sort_values()
    group_ids = group_dates.index.to_numpy()

    n = len(group_ids)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))

    train_ids = set(group_ids[:train_end])
    val_ids = set(group_ids[train_end:val_end])
    test_ids = set(group_ids[val_end:])

    train_df = df[df[group_col].isin(train_ids)].copy()
    val_df = df[df[group_col].isin(val_ids)].copy()
    test_df = df[df[group_col].isin(test_ids)].copy()
    return train_df, val_df, test_df


def make_sample_weight(y: pd.Series) -> pd.Series:
    counts = y.value_counts().sort_index()
    inv = counts.max() / counts
    class_weight = {int(k): float(inv.loc[k]) for k in inv.index}
    return y.map(class_weight)


def build_xgb_model(
    *,
    seed: int,
    n_estimators: int = 1400,
    max_depth: int = 4,
    learning_rate: float = 0.025,
    min_child_weight: float = 4.0,
    subsample: float = 0.85,
    colsample_bytree: float = 0.85,
    gamma: float = 0.0,
    reg_lambda: float = 1.5,
    early_stopping_rounds: int | None = None,
):
    from xgboost import XGBClassifier

    params = dict(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        min_child_weight=min_child_weight,
        subsample=subsample,
        colsample_bytree=colsample_bytree,
        gamma=gamma,
        objective="multi:softprob",
        eval_metric="mlogloss",
        tree_method="hist",
        reg_lambda=reg_lambda,
        random_state=seed,
        n_jobs=0,
    )
    if early_stopping_rounds is not None:
        params["early_stopping_rounds"] = early_stopping_rounds
    return XGBClassifier(**params)


def build_draw_binary_xgb_model(
    *,
    seed: int,
    n_estimators: int = 1400,
    max_depth: int = 4,
    learning_rate: float = 0.025,
    min_child_weight: float = 4.0,
    subsample: float = 0.85,
    colsample_bytree: float = 0.85,
    gamma: float = 0.0,
    reg_lambda: float = 1.5,
    early_stopping_rounds: int | None = None,
):
    from xgboost import XGBClassifier

    params = dict(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        min_child_weight=min_child_weight,
        subsample=subsample,
        colsample_bytree=colsample_bytree,
        gamma=gamma,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        reg_lambda=reg_lambda,
        random_state=seed,
        n_jobs=0,
    )
    if early_stopping_rounds is not None:
        params["early_stopping_rounds"] = early_stopping_rounds
    return XGBClassifier(**params)


def make_draw_target(y: pd.Series) -> pd.Series:
    return (y.astype(int) == DRAW_TARGET).astype(int)


@dataclass
class ModelRun:
    train_df: pd.DataFrame
    test_df: pd.DataFrame
    baseline_pred: np.ndarray
    proba: np.ndarray
    pred: np.ndarray


def fit_and_predict(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    seed: int,
) -> ModelRun:
    X_train = train_df[feature_cols]
    y_train = train_df["target"].astype(int)
    X_test = test_df[feature_cols]

    baseline_class = int(y_train.value_counts().idxmax())
    baseline_pred = np.full(len(test_df), baseline_class, dtype=int)

    sample_weight = make_sample_weight(y_train)
    model = build_xgb_model(seed=seed)
    model.fit(X_train, y_train, sample_weight=sample_weight)

    proba = model.predict_proba(X_test)
    pred = proba.argmax(axis=1)
    return ModelRun(
        train_df=train_df,
        test_df=test_df,
        baseline_pred=baseline_pred,
        proba=proba,
        pred=pred,
    )


def summarize_metrics(y_true: np.ndarray, pred: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    return {
        "acc": float(accuracy_score(y_true, pred)),
        "logloss": float(log_loss(y_true, proba, labels=[0, 1, 2])),
    }


def evaluate_value_bets(
    eval_df: pd.DataFrame,
    proba: np.ndarray,
    ev_threshold: float,
) -> dict[str, float]:
    odds = np.column_stack(
        [
            eval_df["market_away_win_odds_open"].to_numpy(),
            eval_df["market_draw_odds_open"].to_numpy(),
            eval_df["market_home_win_odds_open"].to_numpy(),
        ]
    )

    valid_mask = np.isfinite(odds).all(axis=1) & (odds > 1.0).all(axis=1)
    if not valid_mask.any():
        return {"bets": 0.0, "hit_rate": np.nan, "roi": np.nan, "avg_ev": np.nan}

    fair_probs = 1.0 / odds
    fair_probs = fair_probs / fair_probs.sum(axis=1, keepdims=True)

    expected_value = proba * odds - 1.0
    chosen = expected_value.argmax(axis=1)
    chosen_ev = expected_value[np.arange(len(expected_value)), chosen]
    bet_mask = valid_mask & (chosen_ev > ev_threshold)

    if not bet_mask.any():
        return {"bets": 0.0, "hit_rate": np.nan, "roi": np.nan, "avg_ev": np.nan}

    selected_odds = odds[np.arange(len(odds)), chosen]
    y_true = eval_df["target"].astype(int).to_numpy()
    won = chosen == y_true
    returns = np.where(won, selected_odds - 1.0, -1.0)
    returns = returns[bet_mask]

    return {
        "bets": float(bet_mask.sum()),
        "hit_rate": float(won[bet_mask].mean()),
        "roi": float(returns.mean()),
        "avg_ev": float(chosen_ev[bet_mask].mean()),
        "avg_edge": float(
            (
                proba[np.arange(len(proba)), chosen]
                - fair_probs[np.arange(len(fair_probs)), chosen]
            )[bet_mask].mean()
        ),
    }


def print_full_report(label: str, run: ModelRun) -> None:
    y_true = run.test_df["target"].astype(int).to_numpy()
    baseline_acc = float(accuracy_score(y_true, run.baseline_pred))
    metrics = summarize_metrics(y_true, run.pred, run.proba)

    print(f"{label} baseline acc", baseline_acc)
    print(f"{label} xgb acc", metrics["acc"])
    print(f"{label} xgb logloss", metrics["logloss"])
    print("confusion matrix (rows=true, cols=pred)")
    print(confusion_matrix(y_true, run.pred, labels=[0, 1, 2]))
    print("classification report")
    print(classification_report(y_true, run.pred, target_names=OUTCOME_LABELS, zero_division=0))
