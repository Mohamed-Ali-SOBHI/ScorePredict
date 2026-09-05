"""Produce an auditable French report from the completed challenger tournament."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.portfolio_presets import PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026, SHADOW_DRAW_CONSENSUS_UNWEIGHTED_2026
from train.research_challengers_v2 import BASELINE, ENSEMBLES, PROBS, apply_betting_policy, file_hash, save_json, summarize_bets
from train.evaluate_model_challengers import prediction_metrics


def read_predictions(folder: Path, name: str, years: list[int]) -> pd.DataFrame:
    parts = []
    for year in years:
        if name in ENSEMBLES:
            members = [read_predictions(folder, member, [year]).sort_values("match_id").reset_index(drop=True)
                       for member in ENSEMBLES[name]]
            part = members[0].copy()
            for member in members[1:]:
                if not part.match_id.equals(member.match_id):
                    raise ValueError("Mismatched ensemble identities")
            part[PROBS] = np.mean([p[PROBS].to_numpy() for p in members], axis=0)
        else:
            paths = list((folder / "prediction_cache").glob(f"*/{year}_{name}.csv.gz"))
            if len(paths) != 1:
                raise ValueError(f"Expected exactly one prediction cache for {name}, {year}")
            part = pd.read_csv(paths[0], parse_dates=["date"])
            part = part[part.season == year].copy()
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def paired_loss_difference(candidate: pd.DataFrame, reference: pd.DataFrame) -> dict:
    joined = candidate.merge(reference, on="match_id", suffixes=("_c", "_r"), validate="one_to_one")
    if len(joined) != len(candidate) or len(joined) != len(reference):
        raise ValueError("Predictive comparison requires exactly the same fixtures")
    y = joined.target_c.to_numpy(dtype=int)
    p = joined[[p + "_c" for p in PROBS]].to_numpy()
    q = joined[[p + "_r" for p in PROBS]].to_numpy()
    delta = -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)) + np.log(np.clip(q[np.arange(len(y)), y], 1e-12, 1))
    blocks = pd.DataFrame({"date": joined.date_c.dt.normalize(), "delta": delta}).groupby("date").delta.agg(["sum", "count"])
    rng = np.random.default_rng(20260905)
    indexes = rng.integers(0, len(blocks), size=(5000, len(blocks)))
    values = blocks["sum"].to_numpy()[indexes].sum(axis=1) / blocks["count"].to_numpy()[indexes].sum(axis=1)
    return {"matches": len(y), "mean_log_loss_difference": float(delta.mean()),
            "day_block_interval_95pct": [float(v) for v in np.quantile(values, [.025, .975])],
            "negative_means_candidate_better": True}


def pct(value) -> str:
    return "—" if value is None else f"{100 * value:+.2f} %".replace(".", ",")


def table_row(label: str, entry: dict) -> str:
    return f"| {label} | {entry['bets']} | {entry['profit_units']:+.2f} | {pct(entry['roi'])} |"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="train/output/research_v2_2026_09_05")
    args = parser.parse_args()
    folder = Path(args.folder)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    ranking = []
    for name in report["prediction_results"]:
        frame = read_predictions(folder, name, list(range(2019, 2024)))
        ranking.append({"name": name, "development": prediction_metrics(frame)})
    ranking.sort(key=lambda r: r["development"]["log_loss"])
    prediction_champion = ranking[0]["name"]
    future = read_predictions(folder, prediction_champion, [2024, 2025])
    compared = {name: paired_loss_difference(future, read_predictions(folder, name, [2024, 2025]))
                for name in ("current", "unweighted", "market_only")}
    chosen = report["selection"]["chosen_on_development"]
    portfolios = report["portfolio_results"]
    existing_controls = {BASELINE, "current__legacy", "current__production_fixed", "recency__legacy"}
    eligible_2025 = [(name, p) for name, p in portfolios.items()
                     if p["season_2025"]["bets"] >= 50 and name not in existing_controls
                     and not name.startswith("market_only__")]
    best_2025 = max(eligible_2025, key=lambda item: item[1]["season_2025"]["roi"])
    frozen_decisions = []
    for frozen_rule in SHADOW_DRAW_CONSENSUS_UNWEIGHTED_2026:
        original_rule = next(s for s in PRODUCTION_DRAW_CONSENSUS_NONFAVORITE_2026
                             if (s.bet_league, s.odds_min, s.odds_max) ==
                             (frozen_rule.bet_league, frozen_rule.odds_min, frozen_rule.odds_max))
        frozen_decisions.append({"strategy": original_rule.name, "threshold": frozen_rule.threshold,
                                 "edge_min": frozen_rule.edge_min})
    frozen_reference_bets = apply_betting_policy(read_predictions(folder, "unweighted", [2025]), frozen_decisions)
    frozen_reference = summarize_bets(frozen_reference_bets)
    frozen_reference_bets.to_csv(folder / "frozen_reference_2025_bets.csv", index=False)
    threads = report["manifest"].get("training_threads", 2)
    reproduction_name = "reference_native_threads.json" if threads == 0 else "reference_reproduction_check.json"
    reproduction = json.loads((folder / reproduction_name).read_text(encoding="utf-8"))
    native_check = json.loads((folder / "reference_native_threads.json").read_text(encoding="utf-8"))
    observed_native = native_check["checks"]["unweighted"]["original_evaluator_retuned_filters"]["test"]
    previous_report = json.loads((ROOT / "train/output/model_challenger_evaluation_2017_2025.json").read_text(encoding="utf-8"))
    expected_native = previous_report["latest_untouched_holdout"]["betting_results_filters_retuned_on_validation"]["unweighted"]["test"]
    reference_reproduced = (observed_native["bets"] == expected_native["bets"]
                            and abs(observed_native["profit_units"] - expected_native["profit_units"]) < 1e-8)
    expanded = json.loads((folder / "all_outcomes_report.json").read_text(encoding="utf-8"))
    comparison = {
        "prediction_model_selected_on_2019_2023_log_loss": prediction_champion,
        "prediction_development_ranking": ranking,
        "prediction_confirmation_metrics": prediction_metrics(future),
        "paired_confirmation_comparisons": compared,
        "betting_candidate_selected_on_development": chosen,
        "best_2025_after_looking_at_all_results_not_independent_confirmation": best_2025[0],
        "promoted_to_production": False,
        "baseline_2025": portfolios[BASELINE]["season_2025"],
        "baseline_definition": "Same unweighted models but filters reselected on current 2024 validation data",
        "prior_frozen_shadow_rules_on_current_data_2025": frozen_reference,
        "prior_frozen_shadow_rules": frozen_decisions,
        "prior_report_reproduced_with_native_threads": reference_reproduced,
        "prior_reference_expected": expected_native,
        "prior_reference_reproduced": observed_native,
        "experiment_training_threads": threads,
        "independent_evaluator_max_probability_discrepancy": max(
            max(v["max_probability_difference"].values()) for v in reproduction["checks"].values()),
        "expanded_three_outcome_experiment": {"chosen": expanded["chosen_on_development"],
            "confirmation": expanded["results"][expanded["chosen_on_development"]]["confirmation_2024_2025"]
            if expanded["chosen_on_development"] else None},
        "artifacts_sha256": {p.name: file_hash(p) for p in [folder / "report.json", folder / "dataset_2014_2025.csv.gz",
                                                         folder / "selection_before_confirmation.json", folder / "all_test_bets.csv.gz"]},
    }
    save_json(folder / "comparison.json", comparison)

    lines = ["# Recherche du 5 septembre 2026", "",
             "Les expériences portent sur les mêmes 21 587 matchs historiques, avec une copie des données et une empreinte SHA-256. "
             "Les données 2026 sont exclues. Les 15 variantes de prédiction sont comparées avec trois politiques de pari ; "
             "la référence de production à règles fixes est également conservée.", "",
             "Pour chaque saison T, les modèles sont entraînés jusqu'à T−2 et les filtres réglés sur T−1. "
             "Le candidat de pari est choisi sur les cinq saisons 2019–2023 avant de calculer 2024–2025. "
             "Ces saisons ayant déjà servi à d'autres recherches, il s'agit d'une comparaison rétrospective, pas d'une preuve prospective.", "",
             "## Reproduction de la référence", "",
             f"L'ancien rapport annonçait {pct(expected_native['roi'])} sur {expected_native['bets']} paris. "
             + ("Ce résultat a été reproduit exactement avec l'ancien évaluateur, les données actuelles et sa configuration native de calcul. "
                "Le premier tournoi avait limité les calculs à deux threads : cela a changé les modèles XGBoost, malgré une graine identique. "
                "La différence ne provenait donc pas d'une amélioration du modèle ni de l'ajout des matchs 2026. "
                if reference_reproduced else
                f"La réexécution native donne {pct(observed_native['roi'])} sur {observed_native['bets']} paris : "
                "la référence n'est pas reproduite et aucune supériorité par rapport à l'ancien rapport ne peut être affirmée. ") +
             f"Configuration de CE rapport : {'native (n_jobs=0)' if threads == 0 else str(threads) + ' threads'}. "
             f"Avec les anciens filtres figés, la référence de ce rapport donne {pct(frozen_reference['roi'])} "
             f"sur {frozen_reference['bets']} paris. Les données, les paramètres d'exécution et les prédictions sont désormais archivés.", "",
             "## Pari : saison 2025/26 sur la copie actuelle", "",
             "| Variante | Paris | Gain net (mises identiques) | Rendement |", "|---|---:|---:|---:|",
             table_row("Production actuelle, règles fixes", portfolios["current__production_fixed"]["season_2025"]),
             table_row("Ancienne référence non pondérée, anciens filtres figés", frozen_reference),
             table_row("Même modèle non pondéré, filtres recalculés sur 2024", portfolios[BASELINE]["season_2025"])]
    if chosen:
        lines.append(table_row(f"Candidat choisi avant confirmation : `{chosen}`", portfolios[chosen]["season_2025"]))
    lines.extend([table_row(f"Meilleur résultat 2025 après comparaison : `{best_2025[0]}`", best_2025[1]["season_2025"]), "",
                  "Le meilleur résultat trouvé après consultation des résultats ne constitue pas une validation indépendante. "
                  "Il est distingué du candidat choisi uniquement sur les premières saisons. "
                  f"Cette ligne retient au moins 50 paris ; la référence à filtres recalculés en compte "
                  f"{portfolios[BASELINE]['season_2025']['bets']}.", "", "## Stabilité", "",
                  "| Variante / période | Paris | Gain net | Rendement |", "|---|---:|---:|---:|",
                  table_row("Référence non pondérée, 2019–2025", portfolios[BASELINE]["all_folds"]),
                  table_row("Référence non pondérée, 2024–2025", portfolios[BASELINE]["confirmation_2024_2025"])])
    lines.extend(["", "Dans ce tableau de stabilité, les filtres de la référence sont recalculés chaque année sur la saison précédente. "
                  "Ce n'est pas une application rétrospective des trois seuils de septembre 2026.", "",
                  "| Variante / période | Paris | Gain net | Rendement |", "|---|---:|---:|---:|"])
    if chosen:
        lines.extend([table_row("Candidat choisi, 2019–2025", portfolios[chosen]["all_folds"]),
                      table_row("Candidat choisi, 2024–2025", portfolios[chosen]["confirmation_2024_2025"])])
    else:
        lines.extend(["", "Aucun candidat ne remplit les conditions de sélection sur 2019–2023."])
    for label, name in [("Référence", BASELINE), ("Candidat choisi", chosen)]:
        if name:
            summary = portfolios[name]["confirmation_2024_2025"]
            interval = summary.get("day_block_roi_interval_95pct")
            if interval:
                lines.extend(["", f"{label} : intervalle descriptif du rendement sur 2024–2025 de {pct(interval[0])} à {pct(interval[1])}. "
                              f"Plus forte baisse : {summary['max_drawdown_units']:.2f} mises. "
                              f"Avec des cotes inférieures de 5 % : {pct(summary['roi_with_5pct_shorter_odds'])}."])
    best_summary = best_2025[1]["season_2025"]
    interval = best_summary["day_block_roi_interval_95pct"]
    lines.extend(["", f"Nouvelle variante à {pct(best_summary['roi'])} : intervalle descriptif 2025/26 de "
                  f"{pct(interval[0])} à {pct(interval[1])}. "
                  f"Sur 2019–2023, elle donne {pct(next(r['development']['roi'] for r in report['selection']['development_ranking'] if r['name'] == best_2025[0]))}. "
                  "Elle n'a pas été choisie par le protocole de sélection sur les premières années."])
    if expanded["chosen_on_development"]:
        broad = expanded["results"][expanded["chosen_on_development"]]["confirmation_2024_2025"]
        lines.extend(["", "## Extension aux trois issues", "",
                      f"Le candidat retenu sur les premières années pour jouer domicile/nul/extérieur donne {pct(broad['roi'])} "
                      f"sur {broad['bets']} paris en 2024–2025. Cette extension n'améliore pas la référence. "
                      "Ses seuils, 45 combinaisons et résultats complets sont conservés dans `all_outcomes_report.json`."])
    lines.extend(["", "## Qualité des prédictions", "",
                  f"Modèle choisi par l'erreur de probabilité sur 2019–2023 : `{prediction_champion}`.", "",
                  "| Modèle (2024–2025) | Résultats correctement classés | Erreur de probabilité (plus bas = mieux) | Score moyen des 3 catégories |",
                  "|---|---:|---:|---:|"])
    for name in dict.fromkeys(["current", "unweighted", "market_only", prediction_champion]):
        metrics = report["prediction_results"][name]["confirmation_2024_2025"]
        lines.append(f"| `{name}` | {100*metrics['accuracy']:.2f} % | {metrics['log_loss']:.4f} | {metrics['macro_f1']:.4f} |")
    lines.extend(["", "Les écarts de probabilités sont comparés match par match, avec rééchantillonnage par jour. "
                  "Les intervalles détaillés et les scores par catégorie figurent dans `comparison.json`. "
                  "Les intervalles ne corrigent pas le biais lié aux nombreuses variantes essayées.", "",
                  "## Reproduction", "", "```powershell",
                  f"python train/research_challengers_v2.py --threads {threads} --output {folder.as_posix()}",
                  f"python train/research_all_outcomes_v2.py --folder {folder.as_posix()}",
                  f"python train/check_research_reference.py --folder {folder.as_posix()} " + ("--native-threads" if threads == 0 else ""),
                  f"python train/summarize_research_v2.py --folder {folder.as_posix()}", "```", "",
                  "Le script reprend la copie figée et les prédictions intermédiaires. Il refuse une reprise si le code ou les données archivées ont changé. "
                  "Les essais n'effectuent aucun envoi vers Supabase et ne modifient aucune stratégie publique.", "",
                  f"Empreinte des données : `{report['manifest']['dataset_sha256']}`.", "",
                  "![Comparaison des résultats](comparison.png)"])
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    plot_names = list(dict.fromkeys([BASELINE, chosen, best_2025[0]]))
    plot_names = [name for name in plot_names if name]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), layout="constrained")
    colors = ["#4b5563", "#047857", "#2563eb"]
    labels = {BASELINE: "Non pondéré / filtres annuels", chosen: "Choisi sur 2019–2023",
              best_2025[0]: "Meilleur nouveau 2025 (exploratoire)"}
    bets = pd.read_csv(folder / "all_test_bets.csv.gz", parse_dates=["date"])
    for index, name in enumerate(plot_names):
        p = portfolios[name]["all_folds"]
        years = range(2019, 2026)
        returns = [100*p["by_season"].get(str(year), {}).get("roi", np.nan) for year in years]
        axes[0].bar(np.arange(7) + (index-1)*.25, returns, .25, color=colors[index], label=labels[name])
        selected = bets[(bets.portfolio == name) & (bets.season >= 2024)].sort_values(["date", "match_id"])
        profit = np.where(selected.target == 1, selected.selected_odds - 1, -1)
        if len(selected):
            axes[1].plot(selected.date, np.cumsum(profit), color=colors[index], label=labels[name], linewidth=1.6)
    axes[0].set_xticks(range(7), [f"{y}/{str(y+1)[-2:]}" for y in range(2019, 2026)], rotation=35)
    axes[0].set_title("Rendement par saison", loc="left", fontweight="bold")
    axes[0].set_ylabel("Rendement (%)")
    axes[0].set_xlabel("Barre absente : aucun pari cette saison")
    axes[0].axvline(4.5, color="#9ca3af", linestyle=":")
    axes[1].set_title("Confirmation rétrospective 2024–2025", loc="left", fontweight="bold")
    axes[1].set_ylabel("Gain net cumulé (mises identiques)")
    for ax in axes:
        ax.axhline(0, color="#6b7280", linewidth=.7)
        ax.grid(axis="y", alpha=.15)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle("ScorePredict — comparaison rétrospective avec découpage chronologique", fontsize=12)
    fig.savefig(folder / "comparison.png", dpi=170)
    plt.close(fig)
    print(json.dumps({k: comparison[k] for k in ("prediction_model_selected_on_2019_2023_log_loss",
          "betting_candidate_selected_on_development", "best_2025_after_looking_at_all_results_not_independent_confirmation")}, indent=2))
    print(folder / "summary.md")


if __name__ == "__main__":
    main()
