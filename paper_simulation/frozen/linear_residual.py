"""Fixed-capacity soft/hard-target market-residual classifier.

Caller supplies *preclosing* features and normalized B365 preclosing offset.
The exact same class trains either Avg closing probabilities or outcome one-hots.
All feature preparation is learned from training only. No validation or test
targets enter fit, and no early stopping or hyperparameter search occurs.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp, softmax


def probabilities(values):
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3 or not np.isfinite(arr).all():
        raise ValueError("Expected finite Nx3 probabilities, ordered A/D/H")
    if np.min(arr) < 0 or not np.allclose(arr.sum(axis=1), 1, atol=1e-8):
        raise ValueError("Probabilities must be nonnegative and sum to 1")
    return arr


def objective_gradient(flat, design, offset, targets, penalty):
    beta = flat.reshape(design.shape[1], 3)
    logits = offset + design @ beta
    logp = logits - logsumexp(logits, axis=1, keepdims=True)
    loss = -(targets * logp).sum() / len(design) + .5 * (penalty * beta ** 2).sum()
    grad = design.T @ (np.exp(logp) - targets) / len(design) + penalty * beta
    return float(loss), grad.ravel()


@dataclass
class LinearResidual:
    slope_penalty: float = .05
    intercept_penalty: float = .002
    maxiter: int = 600

    def _transform(self, frame):
        if frame.columns.tolist() != self.columns_:
            raise ValueError("Feature columns changed between training and scoring")
        values = frame.replace([np.inf, -np.inf], np.nan).astype(float).fillna(self.median_)
        normalized = ((values - self.mean_) / self.scale_).clip(-8, 8)
        return np.column_stack([np.ones(len(frame)), normalized.to_numpy()])

    def fit(self, features, market_pre, targets):
        if len(features) != len(market_pre) or len(features) != len(targets) or not len(features):
            raise ValueError("Training rows do not align")
        if any(any(t in str(c).lower() for t in ("close", "closing", "target", "ftr", "ftag", "fthg")) for c in features):
            raise ValueError("Prohibited future/result feature name")
        self.columns_ = features.columns.tolist()
        clean = features.replace([np.inf, -np.inf], np.nan).astype(float)
        self.median_ = clean.median().fillna(0)
        self.mean_ = clean.fillna(self.median_).mean()
        self.scale_ = clean.fillna(self.median_).std().replace(0, 1).fillna(1)
        design = self._transform(features)
        q = probabilities(market_pre)
        if np.min(q) <= 0:
            raise ValueError("Market offset must be strictly positive")
        target = probabilities(targets)
        offset = np.log(q)
        penalty = np.full((design.shape[1], 3), self.slope_penalty)
        penalty[0] = self.intercept_penalty
        result = minimize(objective_gradient, np.zeros(design.shape[1] * 3),
                          args=(design, offset, target, penalty), method="L-BFGS-B", jac=True,
                          options={"maxiter": self.maxiter, "ftol": 1e-12, "gtol": 1e-8})
        if not result.success:
            raise ValueError(f"Unconverged optimizer: {result.message}")
        self.coef_ = result.x.reshape(design.shape[1], 3)
        self.diagnostics_ = {"training_rows": len(features), "features": len(self.columns_),
                             "iterations": int(result.nit), "objective": float(result.fun),
                             "gradient_maxabs": float(np.max(np.abs(result.jac))),
                             "success": bool(result.success)}
        return self

    def predict_proba(self, features, market_pre):
        q = probabilities(market_pre)
        if len(q) != len(features) or np.min(q) <= 0:
            raise ValueError("Invalid scoring market offsets")
        return softmax(np.log(q) + self._transform(features) @ self.coef_, axis=1)

    def audit(self):
        return {**self.diagnostics_, "feature_columns": self.columns_,
                "slope_penalty": self.slope_penalty, "intercept_penalty": self.intercept_penalty,
                "coefficient_columns": ["A", "D", "H"],
                "coefficients": {name: row.tolist() for name, row in zip(["intercept", *self.columns_], self.coef_)},
                "train_median": self.median_.to_dict(), "train_mean": self.mean_.to_dict(),
                "train_scale": self.scale_.to_dict()}
