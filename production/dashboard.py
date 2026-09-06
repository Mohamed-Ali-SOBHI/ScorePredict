from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME, POOLED_RELEASE_MANIFEST
from inference.prediction_window import in_prediction_window


LEAGUE_LABELS = {
    "EPL": "Premier League",
    "La_liga": "La Liga",
    "Bundesliga": "Bundesliga",
    "Serie_A": "Serie A",
    "Ligue_1": "Ligue 1",
}

OUTCOME_LABELS = {
    "draw": "Match nul",
    "home_win": "Victoire domicile",
    "away_win": "Victoire extérieur",
}

PORTFOLIO_LABELS = {
    "validation_multi_strategy_portfolio_2024": "Sélection de référence",
    "exploratory_multi_strategy_portfolio_2025": "Sélection complémentaire",
    "experimental_draw_consensus_nonfavorite_2025": "Sélection complémentaire",
    "experimental_draw_consensus_plus_anti_overconfidence_2025": "Sélection complémentaire",
    "production_draw_consensus_nonfavorite_2026_08_12": "Stratégie championne",
    "production_draw_pooled_unweighted_2026_09_05": "Sélection à filtre commun",
}
DISPLAY_TIMEZONE = ZoneInfo("Europe/Paris")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {
        "",
        "false",
        "0",
        "0.0",
        "no",
        "non",
        "none",
        "nan",
        "<na>",
    }


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _iso(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _match_iso(value: Any) -> str | None:
    """Serialize match times with an explicit Paris offset for every visitor."""
    parsed = _parse_date(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DISPLAY_TIMEZONE)
    else:
        parsed = parsed.astimezone(DISPLAY_TIMEZONE)
    return parsed.isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _file_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _age_days(value: Any, now: datetime) -> float | None:
    parsed = _parse_date(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 86400)


def _risk_label(score: float) -> str:
    if score >= 70:
        return "Élevé"
    if score >= 40:
        return "Modéré"
    return "Faible"


def _status(ok: bool, warning: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warning else "fail"


def _downsample(rows: list[dict[str, Any]], maximum: int = 220) -> list[dict[str, Any]]:
    if len(rows) <= maximum:
        return rows
    stride = (len(rows) - 1) / (maximum - 1)
    indexes = {round(index * stride) for index in range(maximum)}
    return [row for index, row in enumerate(rows) if index in indexes]


@dataclass(frozen=True)
class SourcePaths:
    quality: Path
    team_registry_audit: Path
    scientific: Path
    portfolio_bets: Path
    upcoming_bets: Path
    upcoming_all: Path
    live_log: Path
    live_evaluation: Path
    live_summary: Path
    prediction_store_status: Path
    snapshot: Path

    @classmethod
    def from_root(cls, root: Path) -> "SourcePaths":
        return cls(
            quality=root / "train" / "output" / "data_quality_audit.json",
            team_registry_audit=root / "train" / "output" / "team_registry_audit.json",
            scientific=(
                root
                / "inference/releases/draw_pooled_2026_09_05/benchmark.json"
            ),
            portfolio_bets=(
                root
                / "inference/releases/draw_pooled_2026_09_05/benchmark_bets.csv"
            ),
            upcoming_bets=root / "inference" / "output" / "upcoming_portfolio_bets.csv",
            upcoming_all=root / "inference" / "output" / "upcoming_portfolio_predictions.csv",
            live_log=root / "inference" / "output" / "live_portfolio_bet_log.csv",
            live_evaluation=root / "inference" / "output" / "live_portfolio_evaluation.csv",
            live_summary=root / "inference" / "output" / "live_portfolio_evaluation_summary.json",
            prediction_store_status=root / "inference" / "output" / "prediction_store_status.json",
            snapshot=root / "production" / "static" / "data" / "dashboard.json",
        )


class DashboardService:
    """Builds a safe, cached read model from the existing research exports."""

    def __init__(self, root: Path | str | None = None, ttl_seconds: int | None = None) -> None:
        default_root = Path(__file__).resolve().parents[1]
        self.root = Path(root or os.getenv("SCOREPREDICT_ROOT", default_root)).resolve()
        self.paths = SourcePaths.from_root(self.root)
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _int(
            os.getenv("SCOREPREDICT_DATA_TTL_SECONDS", "30"), 30
        )
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_time = 0.0

    def get_dashboard(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not force and self._cache and time.monotonic() - self._cache_time < self.ttl_seconds:
                return self._cache
            payload = self._build_payload()
            self._cache = payload
            self._cache_time = time.monotonic()
            return payload

    def _has_live_sources(self) -> bool:
        return self.paths.quality.exists() or self.paths.scientific.exists() or self.paths.live_log.exists()

    def _build_payload(self) -> dict[str, Any]:
        if not self._has_live_sources() and self.paths.snapshot.exists():
            snapshot = _read_json(self.paths.snapshot)
            if snapshot:
                snapshot.setdefault("meta", {})["servingMode"] = "snapshot"
                return snapshot

        now = datetime.now(timezone.utc)
        quality = _read_json(self.paths.quality)
        team_registry_audit = _read_json(self.paths.team_registry_audit)
        science = _read_json(self.paths.scientific)
        live_summary = _read_json(self.paths.live_summary)
        prediction_store_status = _read_json(self.paths.prediction_store_status)
        upcoming_rows = _read_csv(self.paths.upcoming_bets)
        upcoming_all = _read_csv(self.paths.upcoming_all)
        live_rows = _read_csv(self.paths.live_evaluation) or _read_csv(self.paths.live_log)
        portfolio_rows = _read_csv(self.paths.portfolio_bets)
        # Never relabel stale exports or retired live results as the new strategy.
        wrong_exports = any(row.get("portfolio_name") != DEFAULT_PORTFOLIO_NAME for row in upcoming_rows)
        upcoming_rows = [row for row in upcoming_rows if row.get("portfolio_name") == DEFAULT_PORTFOLIO_NAME]
        upcoming_all = [row for row in upcoming_all if row.get("portfolio_name") == DEFAULT_PORTFOLIO_NAME]
        live_rows = [row for row in live_rows if row.get("portfolio_name") == DEFAULT_PORTFOLIO_NAME]
        if live_summary.get("portfolio_name") not in (None, DEFAULT_PORTFOLIO_NAME):
            live_summary = {}
        live_summary.setdefault("portfolio_name", DEFAULT_PORTFOLIO_NAME)

        quality_view = self._quality_view(quality, team_registry_audit, now)
        prediction_rows = [{**row, "recommended_bet": True} for row in upcoming_rows]
        current_predictions = self._limit_to_prediction_window(
            self._prediction_view(prediction_rows, now), now
        )
        scored_fixture_count = len(
            {
                (
                    row.get("date", ""),
                    row.get("league", ""),
                    row.get("team_name", ""),
                    row.get("opponent_name", ""),
                )
                for row in upcoming_all
                if row.get("team_name")
            }
        )
        performance = self._performance_view(science, portfolio_rows, live_summary)
        activity = self._activity_view(live_rows)
        active_portfolio = str(live_summary.get("portfolio_name") or "").strip()
        published_rows = [
            {**row, "recommended_bet": True}
            for row in live_rows
            if _bool(row.get("recommended"))
            and str(row.get("result_status") or "pending") not in {"won", "lost", "void"}
            and (not active_portfolio or str(row.get("portfolio_name") or "").strip() == active_portfolio)
        ]
        published_predictions = self._limit_to_prediction_window(
            self._prediction_view(published_rows, now), now
        )
        predictions = self._merge_upcoming_predictions(current_predictions, published_predictions)
        tracking = self._tracking_view(live_summary, activity, prediction_store_status)
        tracking["pendingAll"] = tracking["pending"]
        tracking["pending"] = sum(in_prediction_window(row.get("date"), now) for row in published_rows)
        risk = self._risk_view(quality_view, tracking, current_predictions)

        latest_prediction = _file_mtime(self.paths.upcoming_all) or _file_mtime(self.paths.upcoming_bets)
        meta_status = "ready"
        if quality_view["overallStatus"] != "pass":
            meta_status = "attention"
        if quality_view["criticalFailures"]:
            meta_status = "blocked"
        if wrong_exports:
            meta_status = "blocked"

        return {
            "meta": {
                "product": "ScorePredict",
                "apiVersion": "1.0",
                "generatedAt": now.isoformat(),
                "servingMode": "live-files",
                "status": meta_status,
                "statusLabel": {
                    "ready": "Prêt",
                    "attention": "Attention requise",
                    "blocked": "Publication bloquée",
                }[meta_status],
                "currentSeason": self._current_season(now),
                "latestPredictionAt": latest_prediction.isoformat() if latest_prediction else None,
                "activePortfolio": live_summary.get("portfolio_name"),
                "strategyPolicy": POOLED_RELEASE_MANIFEST["policy"],
                "strategyActivatedAt": POOLED_RELEASE_MANIFEST["activated_at_utc"],
                "trainingMaxSeason": POOLED_RELEASE_MANIFEST["train_max_season"],
                "filterValidationSeason": POOLED_RELEASE_MANIFEST["filter_validation_season"],
                "disclaimer": "Les prévisions sont indicatives : elles aident à comparer les rencontres, sans garantir un résultat.",
            },
            "summary": {
                "upcomingBets": len(predictions),
                "currentRecommendations": len(current_predictions),
                "scoredFixtures": scored_fixture_count,
                "settledLiveBets": _int(live_summary.get("settled_bets"), len(activity)),
                "pendingPredictions": tracking["pending"],
                "wonPredictions": tracking["won"],
                "lostPredictions": tracking["lost"],
                "liveProfitUnits": _float(live_summary.get("profit_units")),
                "liveRoi": _float(live_summary.get("roi_units")),
                "testBets": performance["metrics"]["betCount"],
                "testRoi": performance["metrics"]["roi"],
                "positiveClvRate": performance["metrics"]["positiveClvRate"],
                "maxDrawdown": performance["metrics"]["maxDrawdown"],
            },
            "predictions": predictions,
            "performance": performance,
            "risk": risk,
            "quality": quality_view,
            "tracking": tracking,
            "activity": activity,
        }

    @staticmethod
    def _current_season(now: datetime) -> int:
        return now.year if now.month >= 7 else now.year - 1

    def _quality_view(
        self,
        audit: dict[str, Any],
        team_registry_audit: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        raw = audit.get("raw_data") or {}
        dataset = audit.get("dataset") or {}
        protocol = audit.get("protocol") or {}
        generated_at = audit.get("generated_at")
        age = _age_days(generated_at, now)
        season_max = _int(dataset.get("season_max"), -1)
        current_season = self._current_season(now)
        raw_ok = raw.get("status") == "ok"
        dataset_ok = dataset.get("status") == "ok"
        odds_missing = _int(dataset.get("missing_opening_odds_rows"))
        infinite_multi = _int(dataset.get("feature_infinite_values_multiclass"))
        audit_fresh = age is not None and age <= 7
        registered_season = _int(team_registry_audit.get("season"), -1)
        registered_teams = _int(team_registry_audit.get("total_teams"))
        expected_teams = _int(team_registry_audit.get("expected_total"))
        registry_ready = (
            team_registry_audit.get("status") == "ok"
            and registered_season == current_season
            and registered_teams == expected_teams
            and expected_teams > 0
        )
        season_ready = season_max >= current_season or registry_ready
        upcoming_mtime = _file_mtime(self.paths.upcoming_all)
        upcoming_age_hours = None
        if upcoming_mtime:
            upcoming_age_hours = max(0.0, (now - upcoming_mtime).total_seconds() / 3600)
        upcoming_fresh = upcoming_age_hours is not None and upcoming_age_hours <= 24

        checks = [
            {
                "id": "raw",
                "label": "Données brutes",
                "status": _status(raw_ok),
                "value": f"{_int(raw.get('unique_matches')):,} matchs".replace(",", " "),
                "detail": "Structure et doublons contrôlés par l'audit.",
            },
            {
                "id": "dataset",
                "label": "Dataset modèle",
                "status": _status(dataset_ok),
                "value": f"{_int(dataset.get('rows')):,} lignes".replace(",", " "),
                "detail": f"{_int(dataset.get('feature_count_multiclass'))} variables pré-match.",
            },
            {
                "id": "odds",
                "label": "Cotes d'ouverture",
                "status": _status(odds_missing == 0),
                "value": f"{odds_missing} manquante(s)",
                "detail": "Les closing odds restent exclues de l'entraînement.",
            },
            {
                "id": "features",
                "label": "Valeurs infinies",
                "status": _status(infinite_multi == 0),
                "value": str(infinite_multi),
                "detail": "Contrôle sur les entrées du modèle multiclasses.",
            },
            {
                "id": "season",
                "label": f"Saison {current_season}/{str(current_season + 1)[-2:]}",
                "status": _status(season_ready, warning=True),
                "value": f"{registered_teams}/{expected_teams} clubs" if registry_ready else ("chargée" if season_ready else "à initialiser"),
                "detail": "Tous les clubs de la saison sont présents." if registry_ready else f"Dernière saison disponible : {season_max if season_max >= 0 else 'inconnue'}.",
            },
            {
                "id": "audit",
                "label": "Fraîcheur de l'audit",
                "status": _status(audit_fresh, warning=age is not None),
                "value": f"il y a {age:.0f} j" if age is not None else "indisponible",
                "detail": "Seuil de publication recommandé : 7 jours.",
            },
            {
                "id": "predictions",
                "label": "Export des prédictions",
                "status": _status(upcoming_fresh, warning=True),
                "value": f"il y a {upcoming_age_hours:.0f} h" if upcoming_age_hours is not None else "non généré",
                "detail": "Un export âgé de plus de 24 h n'est jamais présenté comme actuel.",
            },
        ]
        failures = [check for check in checks if check["status"] == "fail"]
        warnings = [check for check in checks if check["status"] == "warn"]
        overall = "fail" if failures else ("warn" if warnings else "pass")
        return {
            "overallStatus": overall,
            "generatedAt": _iso(generated_at),
            "ageDays": round(age, 1) if age is not None else None,
            "dateRange": {"from": _iso(raw.get("date_min")), "to": _iso(raw.get("date_max"))},
            "rawMatches": _int(raw.get("unique_matches")),
            "datasetRows": _int(dataset.get("rows")),
            "completedRows": _int(dataset.get("completed_rows")),
            "features": _int(dataset.get("feature_count_multiclass")),
            "seasonMax": season_max if season_max >= 0 else None,
            "currentSeasonTeams": registered_teams,
            "expectedSeasonTeams": expected_teams,
            "teamRegistryReady": registry_ready,
            "marketProbabilityRange": [
                _float(dataset.get("market_probability_sum_min")),
                _float(dataset.get("market_probability_sum_max")),
            ],
            "protocol": {
                "status": protocol.get("status", "unknown"),
                "folds": protocol.get("folds") or [],
                "topExperiment": (protocol.get("top_experiment") or {}).get("name"),
            },
            "checks": checks,
            "warningCount": len(warnings),
            "criticalFailures": len(failures),
        }

    def _prediction_view(self, rows: Iterable[dict[str, str]], now: datetime) -> list[dict[str, Any]]:
        predictions_by_fixture: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            match_date = _parse_date(row.get("date"))
            if match_date:
                comparable = match_date if match_date.tzinfo else match_date.replace(tzinfo=DISPLAY_TIMEZONE)
                if comparable.astimezone(timezone.utc) < now.replace(minute=0, second=0, microsecond=0):
                    continue
            recommended = _bool(row.get("recommended_bet"))
            probabilities = {
                "home_win": _float(row.get("pred_home_win")),
                "draw": _float(row.get("pred_draw")),
                "away_win": _float(row.get("pred_away_win")),
            }
            predicted_outcome = max(probabilities, key=probabilities.get)
            selected_outcome = row.get("selected_outcome") if recommended else predicted_outcome
            odds_by_outcome = {
                "home_win": _float(row.get("market_home_win_odds_open"), _float(row.get("selected_odds"))),
                "draw": _float(row.get("market_draw_odds_open"), _float(row.get("selected_odds"))),
                "away_win": _float(row.get("market_away_win_odds_open"), _float(row.get("selected_odds"))),
            }
            odds = odds_by_outcome.get(str(selected_outcome), _float(row.get("selected_odds")))
            edge = _float(row.get("edge")) if recommended else 0.0
            probability_columns_present = any(
                str(row.get(column, "")).strip() not in {"", "nan", "None"}
                for column in ("pred_home_win", "pred_draw", "pred_away_win")
            )
            model_probability = (
                probabilities.get(str(selected_outcome), _float(row.get("predicted_probability")))
                if probability_columns_present
                else _float(row.get("predicted_probability"))
            )
            risk_score = min(95.0, max(15.0, 32 + odds * 5 - edge * 70 - model_probability * 12))
            identity = "|".join(
                [str(row.get("date")), str(row.get("league")), str(row.get("team_name")), str(row.get("opponent_name"))]
            )
            fixture_key = (
                str(row.get("date", "")),
                str(row.get("league", "")),
                str(row.get("team_name", "")),
                str(row.get("opponent_name", "")),
            )
            prediction = {
                    "id": hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12],
                    "date": _match_iso(match_date) or str(row.get("date", "")),
                    "league": row.get("league", ""),
                    "leagueLabel": LEAGUE_LABELS.get(row.get("league", ""), row.get("league", "")),
                    "homeTeam": row.get("team_name", ""),
                    "awayTeam": row.get("opponent_name", ""),
                    "outcome": selected_outcome,
                    "outcomeLabel": OUTCOME_LABELS.get(str(selected_outcome), str(selected_outcome)),
                    "odds": odds,
                    "modelProbability": model_probability,
                    "rawModelProbability": _float(row.get("raw_model_probability")),
                    "marketProbability": _float(row.get("market_probability")),
                    "edge": edge,
                    "valueScore": _float(row.get("value_score"), _float(row.get("expected_value"))),
                    "expectedValue": _float(row.get("expected_value")),
                    "stakeEur": _float(row.get("stake_eur")),
                    "potentialProfitEur": _float(row.get("potential_profit_eur_if_win")),
                    "strategy": row.get("strategy_names", ""),
                    "riskScore": round(risk_score),
                    "riskLabel": _risk_label(risk_score),
                    "recommended": recommended,
                    "adviceLabel": "Pari recommandé",
                    "probabilityNote": row.get("probability_note") or "Probabilité brute non calibrée.",
                }
            previous = predictions_by_fixture.get(fixture_key)
            if previous is None or (recommended and not previous["recommended"]):
                predictions_by_fixture[fixture_key] = prediction
        return sorted(predictions_by_fixture.values(), key=lambda row: (row["date"], -row["edge"]))

    @staticmethod
    def _upcoming_prediction_key(prediction: dict[str, Any]) -> tuple[str, str, str, str, str]:
        parsed_date = _parse_date(prediction.get("date"))
        return (
            parsed_date.date().isoformat() if parsed_date else str(prediction.get("date", ""))[:10],
            str(prediction.get("league", "")),
            str(prediction.get("homeTeam", "")).casefold(),
            str(prediction.get("awayTeam", "")).casefold(),
            str(prediction.get("outcome", "")),
        )

    @staticmethod
    def _limit_to_prediction_window(
        predictions: Iterable[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        return [prediction for prediction in predictions if in_prediction_window(prediction.get("date"), now)]

    @classmethod
    def _merge_upcoming_predictions(
        cls,
        current: Iterable[dict[str, Any]],
        published: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for prediction in published:
            merged[cls._upcoming_prediction_key(prediction)] = {
                **prediction,
                "isCurrentRecommendation": False,
                "adviceLabel": "Pari déjà publié",
            }
        for prediction in current:
            merged[cls._upcoming_prediction_key(prediction)] = {
                **prediction,
                "isCurrentRecommendation": True,
                "adviceLabel": "Pari recommandé aujourd’hui",
            }
        return sorted(merged.values(), key=lambda row: (str(row.get("date", "")), -_float(row.get("edge"))))

    def _performance_view(
        self,
        science: dict[str, Any],
        portfolio_rows: list[dict[str, str]],
        live_summary: dict[str, Any],
    ) -> dict[str, Any]:
        metrics = science.get("metrics") or {}
        clv = science.get("clv_metrics") or {}
        cumulative = 0.0
        peak = 0.0
        curve: list[dict[str, Any]] = []
        dated_rows = sorted(portfolio_rows, key=lambda row: str(row.get("date", "")))
        for row in dated_rows:
            cumulative += _float(row.get("profit"))
            peak = max(peak, cumulative)
            curve.append(
                {
                    "date": (_parse_date(row.get("date")) or datetime.min).date().isoformat(),
                    "value": round(cumulative, 2),
                    "drawdown": round(cumulative - peak, 2),
                }
            )
        verdict = science.get("verdict") or {}
        return {
            "scope": {
                "label": (science.get("scope") or {}).get("label", "Test historique"),
                "startDate": metrics.get("start_date"),
                "endDate": metrics.get("end_date"),
                "selectionMode": science.get("selection_mode", "unknown"),
                "strategyCount": _int(science.get("strategy_count")),
            },
            "metrics": {
                "betCount": _int(metrics.get("bet_count")),
                "profit": _float(metrics.get("total_profit")),
                "roi": _float(metrics.get("roi")),
                "roiCiLow": _float(metrics.get("roi_ci_low")),
                "roiCiHigh": _float(metrics.get("roi_ci_high")),
                "bootstrapPositive": _float(metrics.get("bootstrap_prob_roi_positive")),
                "hitRate": _float(metrics.get("hit_rate")),
                "averageOdds": _float(metrics.get("avg_odds")),
                "averageEdge": _float(metrics.get("avg_edge")),
                "maxDrawdown": _float(metrics.get("max_drawdown")),
                "longestLosingStreak": _int(metrics.get("longest_losing_streak")),
                "positiveClvRate": _float(clv.get("positive_clv_rate")),
                "averageClvOddsDiff": _float(clv.get("avg_clv_odds_diff")),
            },
            "live": {
                "settledBets": _int(live_summary.get("settled_bets")),
                "wonBets": _int(live_summary.get("won_bets")),
                "profitUnits": _float(live_summary.get("profit_units")),
                "roi": _float(live_summary.get("roi_units")),
                "asOf": live_summary.get("as_of_date"),
            },
            "evidence": {
                "level": verdict.get("evidence_level", "non évaluée"),
                "strengths": verdict.get("strengths") or [],
                "risks": verdict.get("risks") or [],
            },
            "curve": _downsample(curve),
            "monthly": science.get("monthly_rows") or [],
            "leagues": [
                {**row, "leagueLabel": LEAGUE_LABELS.get(row.get("league", ""), row.get("league", ""))}
                for row in (science.get("league_rows") or [])
            ],
        }

    @staticmethod
    def _risk_view(
        quality: dict[str, Any],
        tracking: dict[str, Any],
        predictions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        audit_age = quality.get("ageDays")
        verified = _int(tracking.get("verified"))
        pending = _int(tracking.get("pending"))
        advised = sum(bool(prediction.get("recommended")) for prediction in predictions)
        history_risk = max(0.0, 40.0 * (1 - min(verified / 100, 1)))
        advice_risk = 25.0 if predictions and advised == 0 else 8.0
        pending_risk = min(15.0, pending * 1.5)
        freshness_risk = 20.0 if audit_age is None else min(20.0, _float(audit_age) / 7 * 20)
        score = min(100.0, history_risk + advice_risk + pending_risk + freshness_risk)
        components = [
            {"label": "Résultats réellement vérifiés", "score": round(history_risk), "max": 40, "detail": f"{verified} prévision(s) disposent aujourd'hui d'un score final."},
            {"label": "Paris recommandés à venir", "score": round(advice_risk), "max": 25, "detail": f"{advised} pari(s) recommandé(s) parmi {len(predictions)} sélection(s) publiée(s)."},
            {"label": "Rencontres encore en attente", "score": round(pending_risk), "max": 15, "detail": f"{pending} prévision(s) seront vérifiées après le match."},
            {"label": "Données récentes", "score": round(freshness_risk), "max": 20, "detail": "Les données sont récentes." if freshness_risk < 8 else "Une nouvelle collecte est recommandée."},
        ]
        season_ready = bool(quality.get("teamRegistryReady"))
        if not season_ready:
            recommendation = "Attendre la mise à jour de la saison avant de suivre une prévision."
        elif advised == 0:
            recommendation = "Aucun choix n'est conseillé ce week-end. Les rencontres affichées sont uniquement des tendances à observer."
        else:
            recommendation = "Commencer prudemment : une prévision reste incertaine même lorsqu'elle est conseillée."
        return {
            "score": round(score),
            "label": _risk_label(score),
            "components": components,
            "method": "Indice de prudence de 0 à 100 : plus il est élevé, plus il faut attendre et observer avant de suivre un nouveau choix.",
            "recommendation": recommendation,
        }

    @staticmethod
    def _tracking_view(
        summary: dict[str, Any],
        activity: list[dict[str, Any]],
        store_status: dict[str, Any],
    ) -> dict[str, Any]:
        won = _int(summary.get("won_bets"), sum(row["status"] == "won" for row in activity))
        lost = _int(summary.get("lost_bets"), sum(row["status"] == "lost" for row in activity))
        void = _int(summary.get("void_bets"), sum(row["status"] == "void" for row in activity))
        pending_default = sum(row["status"] not in {"won", "lost", "void"} for row in activity)
        pending = (
            _int(summary.get("pending_bets"))
            + _int(summary.get("pending_data_refresh_bets"))
            + _int(summary.get("unmatched_bets"))
        )
        if not summary:
            pending = pending_default
        verified = won + lost
        configured = bool(store_status.get("configured")) and store_status.get("backend") == "supabase"
        return {
            "pending": pending,
            "verified": verified,
            "won": won,
            "lost": lost,
            "void": void,
            "hitRate": won / verified if verified else None,
            "storageReady": configured,
            "storageLabel": "Mémoire Supabase" if configured else "Mémoire locale",
            "storageCopy": (
                "Chaque prévision et son résultat sont conservés entre les exécutions GitHub."
                if configured
                else "Le suivi fonctionne sur cette machine. Ajoutez les secrets Supabase à GitHub pour le rendre permanent."
            ),
            "lastSyncAt": store_status.get("lastSyncAt"),
        }

    @staticmethod
    def _activity_view(rows: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
        activity: list[dict[str, Any]] = []
        for row in rows:
            result_status = row.get("result_status") or ("won" if _bool(row.get("won_live_bet")) else "lost")
            home_score = row.get("actual_home_score")
            away_score = row.get("actual_away_score")
            actual_score = (
                f"{_int(home_score)} - {_int(away_score)}"
                if str(home_score).strip() not in {"", "nan", "<NA>"}
                and str(away_score).strip() not in {"", "nan", "<NA>"}
                else None
            )
            identity = str(row.get("snapshot_key") or "|").encode("utf-8")
            activity.append(
                {
                    "id": hashlib.sha1(identity).hexdigest()[:12],
                    "date": _match_iso(row.get("date")) or row.get("date"),
                    "league": row.get("league", ""),
                    "leagueLabel": LEAGUE_LABELS.get(row.get("league", ""), row.get("league", "")),
                    "homeTeam": row.get("team_name", ""),
                    "awayTeam": row.get("opponent_name", ""),
                    "outcomeLabel": OUTCOME_LABELS.get(row.get("selected_outcome", ""), row.get("selected_outcome", "")),
                    "portfolioLabel": PORTFOLIO_LABELS.get(
                        row.get("portfolio_name", ""), row.get("portfolio_name", "Portefeuille live")
                    ),
                    "odds": _float(row.get("selected_odds")),
                    "status": result_status,
                    "actualScore": actual_score,
                    "recommended": _bool(row.get("recommended")),
                    "profitUnits": _float(row.get("realized_profit_units"), _float(row.get("realized_profit"))),
                }
            )
        unique: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        status_priority = {"won": 3, "lost": 3, "void": 3, "pending_data_refresh": 2, "unmatched": 1, "pending": 0}
        for row in activity:
            parsed_date = _parse_date(row.get("date"))
            key = (
                parsed_date.date().isoformat() if parsed_date else str(row.get("date", ""))[:10],
                str(row.get("league", "")),
                str(row.get("homeTeam", "")).casefold(),
                str(row.get("awayTeam", "")).casefold(),
                str(row.get("outcomeLabel", "")),
            )
            previous = unique.get(key)
            if previous is None:
                unique[key] = row
                continue
            previous_priority = status_priority.get(str(previous.get("status")), 0)
            current_priority = status_priority.get(str(row.get("status")), 0)
            if current_priority > previous_priority or (
                current_priority == previous_priority
                and str(row.get("date", "")) > str(previous.get("date", ""))
            ):
                unique[key] = row
        ordered = sorted(unique.values(), key=lambda row: str(row.get("date", "")), reverse=True)
        # Keep every unresolved choice so the client can scope counts at Paris midnight.
        completed = [row for row in ordered if row["status"] in {"won", "lost", "void"}][:30]
        unresolved = [row for row in ordered if row["status"] not in {"won", "lost", "void"}]
        return sorted(unresolved + completed, key=lambda row: str(row.get("date", "")), reverse=True)


def write_snapshot(service: DashboardService, output: Path | None = None) -> Path:
    target = output or service.paths.snapshot
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = service.get_dashboard(force=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target
