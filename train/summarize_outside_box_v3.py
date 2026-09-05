"""Describe all exploratory findings, including failed ideas and selection bias."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train.research_all_outcomes_v2 import load_frame
from train.research_challengers_v2 import apply_betting_policy, file_hash, save_json, summarize_bets

NATIVE = ROOT / "train/output/research_v2_native_2026_09_05"
ALTERED = ROOT / "train/output/research_v2_2026_09_05"
OUTPUT = ROOT / "train/output/research_outside_box_v3_2026_09_05"
BASELINE = "unweighted__legacy"
POOLED = "unweighted__pooled_cautious"


def percent(value):
    return "aucun pari" if value is None else f"{value * 100:+.2f} %".replace(".", ",")


def paired_roi_difference(candidate, reference):
    """Paired day-block descriptive interval, sharing resampled dates."""
    blocks = []
    for frame in (candidate, reference):
        profit = np.where(frame.target == 1, frame.selected_odds - 1, -1)
        blocks.append(frame.assign(profit=profit).groupby(frame.date.dt.normalize()).profit.agg(["sum", "count"]))
    joined = blocks[0].join(blocks[1], how="outer", lsuffix="_c", rsuffix="_r").fillna(0)
    data = joined[["sum_c", "count_c", "sum_r", "count_r"]].to_numpy()
    rng = np.random.default_rng(20260905)
    draws = data[rng.integers(0, len(data), size=(10000, len(data)))].sum(axis=1)
    valid = (draws[:, 1] > 0) & (draws[:, 3] > 0)
    delta = draws[valid, 0] / draws[valid, 1] - draws[valid, 2] / draws[valid, 3]
    totals = data.sum(axis=0)
    return {"roi_difference": float(totals[0]/totals[1] - totals[2]/totals[3]),
            "interval_95pct": np.quantile(delta, [.025, .975]).tolist(),
            "not_adjusted_for_multiple_comparisons": True}


def main():
    native = json.loads((NATIVE / "report.json").read_text(encoding="utf-8"))
    unusual = json.loads((OUTPUT / "report.json").read_text(encoding="utf-8"))
    native_bets = pd.read_csv(NATIVE / "all_test_bets.csv.gz", parse_dates=["date"])
    odd_bets = pd.read_csv(OUTPUT / "all_test_bets.csv.gz", parse_dates=["date"])
    settings = json.loads((NATIVE / "fold_2025.json").read_text(encoding="utf-8"))["decisions"][POOLED]
    sensitivity = {}
    for label, folder, model in (("native_seed42", NATIVE, "unweighted"),
                                  ("two_threads_seed42", ALTERED, "unweighted"),
                                  ("native_mean_seeds42_73_2026", NATIVE, "unweighted_ensemble")):
        frame = load_frame(folder, model, 2025)
        selected = apply_betting_policy(frame[frame.season == 2025], settings)
        sensitivity[label] = summarize_bets(selected)
    chosen = native_bets[(native_bets.portfolio == POOLED) & (native_bets.season >= 2024)]
    base = native_bets[(native_bets.portfolio == BASELINE) & (native_bets.season >= 2024)]
    concentration = {league: summarize_bets(chosen[chosen.league != league]) for league in sorted(chosen.league.unique())}
    paired = paired_roi_difference(chosen, base)
    robustness = {"source_sha256": file_hash(Path(__file__)), "filter_source": "2024 validation only, native reference",
                  "same_frozen_filter_runtime_and_seed_sensitivity_2025": sensitivity,
                  "paired_roi_difference_2024_2025": paired,
                  "leave_one_league_out_2024_2025": concentration,
                  "production_modified": False, "future_models_frozen": False}
    save_json(OUTPUT / "robustness.json", robustness)

    reference = native["portfolio_results"][BASELINE]
    candidate = native["portfolio_results"][POOLED]
    rows = [("Référence reproduite", reference["season_2025"], reference["confirmation_2024_2025"]),
            ("Même modèle, filtre commun plus prudent", candidate["season_2025"], candidate["confirmation_2024_2025"])]
    for label, name in (("Scores de buts : Poisson linéaire", "poisson_linear__fixed_ev_5pct"),
                         ("Scores de buts : arbres", "poisson_boosted__fixed_ev_5pct"),
                         ("Accord entre deux configurations de calcul", "runtime_cautious__pooled_cautious"),
                         ("Correcteur des erreurs passées : veto", "meta_veto_reference"),
                         ("Diversité des modèles, filtre simple", "diversity_cautious__fixed_ev_5pct")):
        scores = unusual["portfolios"][name]
        rows.append((label, scores["season_2025"], scores["confirmation_2024_2025"]))
    lines = ["# ScorePredict — recherche et pistes hors des sentiers battus", "",
             "## Verdict", "",
             "Plusieurs variantes dépassent la référence à +19,59 % sur 2025/26. Aucune n'est un remplaçant validé : "
             "les meilleures lignes sont choisies après comparaison de nombreuses expériences et leur stabilité ancienne est insuffisante. "
             "La production, les mises et les publications restent inchangées.", "",
             "## Comparaison à mises identiques", "",
             "Le rendement est le gain net divisé par les mises engagées, pas la croissance d'une bankroll. "
             "Les cotes utilisées sont celles d'ouverture ; leur disponibilité réelle, les frais et les limites ne sont pas simulés. "
             "2025 désigne la saison 2025/26. Les périmètres de championnat et de cotes restent ceux des quatre règles d'origine.", "",
             "| Approche | Paris 2025/26 | Rendement 2025/26 | Gain net | Paris sur 2024/25–2025/26 | Rendement sur ces deux saisons |",
             "|---|---:|---:|---:|---:|---:|"]
    for label, last, both in rows:
        lines.append(f"| {label} | {last['bets']} | {percent(last['roi'])} | {last['profit_units']:+.2f} mises | {both['bets']} | {percent(both['roi'])} |")
    lines += ["", "## Ce qui est réellement nouveau", "",
              "1. **Un filtre partagé plutôt que quatre optimisations isolées.** Même modèle non pondéré, mais un seuil commun "
              "sélectionné sur la saison précédente, avec au moins 60 paris de validation et une pénalité pour l'incertitude. "
              "En 2025/26 : espérance estimée supérieure à 15 % et écart d'au moins 4 points au marché. "
              "Il fait +50,68 % sur 63 paris, et +45,02 % sur 59 paris la saison précédente. "
              "Mais il ne publie aucun pari entre 2019 et 2023 : sa fiabilité n'y est donc pas établie. "
              "Il n'a pas été retenu par la sélection sur ces années.", "",
              "2. **Prédire les buts plutôt que directement le vainqueur.** Deux modèles apprennent séparément les buts "
              "domicile/extérieur ; des distributions de Poisson donnent ensuite domicile/nul/extérieur. "
              "Les scores finaux sont seulement des cibles d'entraînement, jamais des variables pré-match. "
              "Le modèle linéaire fait +80,62 % sur seulement 29 paris (9 gagnants), contre −2,03 % sur 118 paris en 2021–2023. "
              "Son intervalle descriptif 2025/26 va de −14,37 % à +192,91 % : l'incertitude reste énorme.", "",
              "3. **Transformer l'instabilité en signal de prudence.** Deux entraînements à graine identique mais à nombres "
              "de threads différents sont combinés en retenant leur signal le plus prudent. "
              "Avec le filtre commun, +30,73 % sur 60 paris en 2025/26, mais −45,48 % sur les 66 paris publiés en 2021–2023. "
              "C'est un stress-test de stabilité, pas une probabilité de confiance certifiée.", "",
              "4. **Apprendre des erreurs déjà observées.** Un second modèle lit seulement les anciennes probabilités "
              "produites hors entraînement, les cotes, le championnat et le désaccord des modèles. "
              "Il est entraîné au plus jusqu'à T−2 ; les filtres utilisent T−1. Comme veto, il garde 48 paris "
              "et atteint +27,63 % en 2025/26, mais son gain total est inférieur à la référence : +13,26 contre +15,48 mises.", "",
              "5. **Jouer aussi domicile/extérieur.** Le candidat choisi sur 2019–2023 fait −2,73 % en 2025/26 "
              "(306 paris), et +1,83 % sur 2024/25–2025/26 (673 paris). Cette diversification n'améliore pas le rendement de référence.", "",
              "## Le problème de stabilité du meilleur filtre", "",
              "Voici exactement les mêmes seuils, conservés sans nouveau réglage, appliqués à d'autres exécutions du modèle :", "",
              "| Configuration, saison 2025/26 | Paris | Rendement |", "|---|---:|---:|"]
    for label, score in sensitivity.items():
        lines.append(f"| {label} | {score['bets']} | {percent(score['roi'])} |")
    lines += ["", "Le benchmark historique initial a été reproduit deux fois à 79 paris et +19,59 %, "
              "dont une nouvelle fois après restauration de l'environnement Python. Les anciens écarts provenaient de la limitation "
              "des threads introduite dans le premier tournoi. Cela ne justifie pas de changer de configuration pour retenir celle "
              "qui gagne le plus sur le test.", "",
              "Pour le filtre commun sur 2024/25–2025/26 : le rendement descriptif est +47,94 % et son intervalle "
              "à 95 % est [+10,72 % ; +84,65 %]. Cette fourchette ne corrige pas la recherche parmi de nombreux candidats. "
              f"L'écart apparié avec la référence est {paired['roi_difference']*100:+.2f} points de rendement, avec une fourchette "
              f"[{paired['interval_95pct'][0]*100:+.2f} ; {paired['interval_95pct'][1]*100:+.2f}] points.", "",
              "## Qualité des prédictions : autre objectif que le rendement", "",
              "Même ensemble de 1 066 rencontres en 2025/26. Le score logarithmique pénalise les probabilités trop sûres et fausses ; plus bas est meilleur.", "",
              "| Modèle | Résultat le plus probable correct | Score logarithmique | F1 du nul |", "|---|---:|---:|---:|"]
    for label, score in [("Marché sans apprentissage", native["prediction_results"]["market_only"]["season_2025"]),
                          ("Référence non pondérée", native["prediction_results"]["unweighted"]["season_2025"]),
                          *[(name, unusual["prediction_results"][name]["season_2025"])
                            for name in ("poisson_linear", "poisson_boosted", "meta_draw")]]:
        lines.append(f"| {label} | {score['accuracy']*100:.2f} % | {score['log_loss']:.4f} | {score['classes']['draw']['f1']:.4f} |")
    lines += ["", "Les scores par catégorie (précision, rappel, F1) sont conservés dans les rapports JSON. "
              "Un bon rendement sur un petit sous-ensemble ne démontre pas que le modèle prédit mieux tous les matchs. "
              "Les modèles de buts ne classent aucun nul en première position sur cette saison (F1 du nul nul), "
              "mais peuvent lui attribuer une probabilité assez élevée par rapport à la cote pour déclencher un pari.", "",
              "## Ce que je garderais pour la suite", "",
              "Conserver la référence et comparer séparément, sans mise réelle supplémentaire, le filtre commun prudent et le "
              "modèle de scores linéaire. Geler modèle, variables, versions, politique de réentraînement et filtres avant "
              "de regarder les nouveaux résultats. Garder toutes les décisions et abstentions. "
              "Ne pas promouvoir un candidat dès qu'il passe devant sur quelques matchs.", "",
              "Aucun des nouveaux candidats ne satisfait le critère préfixé : au moins 150 paris et trois saisons positives "
              "sur 2021–2023. Aucune stratégie n'a été activée. Le suivi futur ci-dessus est une proposition, pas un service lancé.", "",
              "## Traçabilité", "",
              "- 21 587 matchs étiquetés, saisons 2014–2025 ; 2026 exclue. Copie compressée et SHA-256 conservées.",
              "- Scores réels recoupés avec la cible figée pour chacun des 21 587 matchs ; conflit ou absence bloque le calcul.",
              "- Modèles entraînés jusqu'à T−2, choix des filtres sur T−1, évaluation sur T ; aucune cote de clôture dans les variables.",
              "- Sélection avant calcul des dernières saisons enregistrée dans `selection_before_confirmation.json`.",
              "- Historique déjà exploré : aucun de ces backtests ne constitue un nouvel échantillon vierge.",
              "- Rapports de tous les essais, y compris pertes et abstentions, conservés dans les trois dossiers de recherche.",
              "- Versions de recherche dans `train/requirements-research.txt` ; configuration native 20 threads archivée.",
              "- Scripts de cette passe : `research_outside_box_v3.py` et `summarize_outside_box_v3.py`.",
              "- Contrôle final du 5 septembre 2026 : 96 tests automatisés réussis, dont 14 tests des scripts de recherche.", ""]
    (OUTPUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), layout="constrained")
    series = [("Référence", native_bets[native_bets.portfolio == BASELINE], "#6a7480"),
              ("Filtre commun (exploratoire)", native_bets[native_bets.portfolio == POOLED], "#126747"),
              ("Scores Poisson (exploratoire)", odd_bets[odd_bets.portfolio == "poisson_linear__fixed_ev_5pct"], "#c17b27")]
    for label, frame, color in series:
        selected = frame[frame.season >= 2024].sort_values(["date", "match_id"])
        profit = np.where(selected.target == 1, selected.selected_odds - 1, -1)
        axes[0].plot(selected.date, np.cumsum(profit), label=label, color=color, linewidth=1.6)
    labels = ["Référence", "Filtre commun", "Scores Poisson"]
    positions = np.arange(3)
    for year, offset, alpha in ((2024, -.18, .5), (2025, .18, 1)):
        returns = [summarize_bets(frame[frame.season == year], bootstrap=False)["roi"]*100 for _, frame, _ in series]
        axes[1].bar(positions + offset, returns, .34, color=[s[2] for s in series], alpha=alpha,
                    label=f"{year}/{str(year+1)[-2:]}")
    axes[1].set_xticks(positions, labels)
    axes[1].legend(frameon=False)
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_title("Gain net à mises identiques — deux saisons")
    axes[0].set_ylabel("Mises nettes")
    axes[1].set_title("Rendement par saison")
    axes[1].set_ylabel("% des mises engagées")
    for ax in axes:
        ax.axhline(0, color="#b4b8b6", linewidth=.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.12)
    fig.suptitle("Résultats historiques exploratoires — aucune promotion en production", fontsize=12)
    fig.savefig(OUTPUT / "comparison.png", dpi=150)
    plt.close(fig)
    print(json.dumps({"same_frozen_filter_sensitivity": {n: {k: s[k] for k in ("bets", "roi")} for n, s in sensitivity.items()},
                      "paired_difference": paired, "report": str(OUTPUT / "summary.md")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
