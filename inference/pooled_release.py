"""Load a sealed portable model release. A missing/corrupt release NEVER triggers refit."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from inference.portfolio_presets import PRODUCTION_PORTFOLIO_NAME, PRODUCTION_RELEASE_PATH


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_release(path=PRODUCTION_RELEASE_PATH):
    root = Path(path).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["portfolio_name"] != PRODUCTION_PORTFOLIO_NAME or manifest["policy"] != "unweighted__pooled_cautious":
        raise ValueError("Wrong production portfolio or policy")
    if manifest["train_max_season"] >= manifest["filter_validation_season"] or manifest["filter_validation_season"] >= manifest["live_season"]:
        raise ValueError("Invalid train/calibration/live chronology")
    if manifest.get("auto_retraining_allowed") is not False:
        raise ValueError("The public release must forbid automatic retraining")
    names = set()
    gates = set()
    for entry in manifest["entries"]:
        strategy = entry["strategy"]
        if strategy["name"] in names or strategy["training_weight_mode"] != "unweighted":
            raise ValueError("Duplicate strategy or wrong training weights")
        names.add(strategy["name"])
        gates.add((strategy["threshold"], strategy["edge_min"]))
        for model in entry["models"].values():
            candidate = (root / model["file"]).resolve()
            if candidate.parent != root or digest(candidate) != model["sha256"]:
                raise ValueError("Sealed model is missing, modified or outside the release")
    if len(names) != 4 or len(gates) != 1:
        raise ValueError("The pooled release must contain four domains with one common filter")
    for filename, field in (("benchmark.json", "benchmark_sha256"), ("benchmark_bets.csv", "benchmark_bets_sha256")):
        if digest(root / filename) != manifest[field]:
            raise ValueError("Historical benchmark does not match the release")
    return manifest


def load_release_models(strategies, *, train_max_season, force_retrain=False, path=PRODUCTION_RELEASE_PATH):
    if force_retrain:
        raise ValueError("Public models are sealed. Build a new version instead of --retrain-models")
    manifest = validate_release(path)
    if train_max_season != manifest["train_max_season"]:
        raise ValueError("Training season differs from the sealed release")
    expected = {entry["strategy"]["name"]: entry for entry in manifest["entries"]}
    if {s.name: asdict(s) for s in strategies} != {name: entry["strategy"] for name, entry in expected.items()}:
        raise ValueError("Production filters differ from the sealed release")
    from xgboost import XGBClassifier
    from inference.upcoming_portfolio_strategy import ModelBundle
    bundles = {}
    for name, entry in expected.items():
        models = []
        for kind in ("primary", "secondary"):
            model = XGBClassifier(n_jobs=1)
            model.load_model(Path(path) / entry["models"][kind]["file"])
            models.append(model)
        bundles[name] = ModelBundle(
            model_variant="draw_consensus", train_league=entry["strategy"]["train_league"],
            train_max_season=train_max_season, model=models[0], secondary_model=models[1],
            feature_cols=entry["models"]["primary"]["features"],
            secondary_feature_cols=entry["models"]["secondary"]["features"],
        )
    return bundles, "sealed_release"


if __name__ == "__main__":
    print(json.dumps({"validated": validate_release()["portfolio_name"]}))
