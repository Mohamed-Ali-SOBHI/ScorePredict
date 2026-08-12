from __future__ import annotations

from datetime import date, datetime

from validation_context import ValidationContext
from validation_verdict import ValidationVerdict


MONTH_NAMES_FR = {
    1: "janvier",
    2: "fevrier",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "aout",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "decembre",
}


def format_date_fr(day_value) -> str:
    return f"{day_value.day} {MONTH_NAMES_FR[day_value.month]} {day_value.year}"


def render_group_lines(rows: list[dict], *, key: str, empty_label: str) -> list[str]:
    if not rows:
        return [f"- {empty_label}"]
    return [
        f"- `{row[key]}` : `{row['bets']}` paris, ROI `{row['roi']*100:.2f}%`, profit `{row['profit']:.2f}`"
        for row in rows
    ]


def render_verdict_lines(items: list[str], *, fallback: str) -> list[str]:
    if not items:
        return [f"- {fallback}"]
    return [f"- {item}" for item in items]


def format_percent(value) -> str:
    if value is None:
        return "N/A"
    return f"{value*100:.2f}%"


def format_decimal(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def format_units(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def parse_iso_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def build_next_step_text(context: ValidationContext, metrics: dict) -> str:
    current_date_text = format_date_fr(context.current_date)
    end_date = parse_iso_date(metrics.get("end_date"))
    if end_date is not None and context.current_date > end_date:
        end_date_text = format_date_fr(end_date)
        return (
            f"Comme le rapport est genere le {current_date_text} et que le dernier match "
            f"analyse date du {end_date_text}, cette periode de test est deja terminee. "
            "Le prochain test propre consiste a geler une strategie avant les prochains matchs "
            "futurs, puis a ne l'evaluer que sur les paris generes apres cette date de gel."
        )

    return (
        f"Comme nous sommes le {current_date_text}, le test prospectif propre consiste a "
        "geler la strategie maintenant et a n'evaluer que les matchs joues apres cette date."
    )


def build_markdown_report(
    *,
    context: ValidationContext,
    metrics: dict,
    clv_metrics: dict,
    verdict: ValidationVerdict,
    monthly_rows: list[dict],
    league_rows: list[dict],
    strategy_rows: list[dict],
) -> str:
    summary_text = str(context.summary_path) if context.summary_path else "None"
    strategy_key = "strategy_name" if strategy_rows and "strategy_name" in strategy_rows[0] else "strategy_names"

    monthly_lines = render_group_lines(
        monthly_rows,
        key="month",
        empty_label="Aucun regroupement mensuel disponible.",
    )
    league_lines = render_group_lines(
        league_rows[:8],
        key="league",
        empty_label="Aucun regroupement par ligue disponible.",
    )
    strategy_lines = render_group_lines(
        strategy_rows[:8],
        key=strategy_key,
        empty_label="Aucun regroupement par strategie disponible.",
    )
    strength_lines = render_verdict_lines(verdict.strengths, fallback="Aucun point fort net.")
    risk_lines = render_verdict_lines(verdict.risks, fallback="Aucun risque majeur identifie.")
    clv_coverage_text = (
        f"{clv_metrics['matched_bet_count']}/{metrics['bet_count']} ({format_percent(clv_metrics['matched_coverage'])})"
        if clv_metrics.get("matched_bet_count") is not None
        else "N/A"
    )

    next_step = build_next_step_text(context, metrics)

    return f"""# Rapport de validation scientifique

## Snapshot

- Date du rapport : `{context.current_date.isoformat()}`
- Fichier paris : `{context.bets_path}`
- Fichier resume : `{summary_text}`
- Mode de selection detecte : `{context.selection_mode}`
- Nombre de strategies selectionnees : `{context.strategy_count if context.strategy_count is not None else 'unknown'}`

## Chiffres cles

- Nombre de paris : `{metrics['bet_count']}`
- Profit total : `{metrics['total_profit']:.2f}` unites
- ROI moyen : `{format_percent(metrics['roi'])}`
- IC bootstrap 95% du ROI : `[{format_percent(metrics['roi_ci_low'])}; {format_percent(metrics['roi_ci_high'])}]`
- Proba bootstrap que le ROI soit > 0 : `{format_percent(metrics['bootstrap_prob_roi_positive'])}`
- Hit rate : `{format_percent(metrics['hit_rate'])}`
- IC bootstrap 95% du hit rate : `[{format_percent(metrics['hit_rate_ci_low'])}; {format_percent(metrics['hit_rate_ci_high'])}]`
- Cote moyenne : `{format_units(metrics['avg_odds'])}`
- Edge moyen : `{format_decimal(metrics['avg_edge'])}`
- EV moyen : `{format_decimal(metrics['avg_expected_value'])}`
- Max drawdown : `{format_units(metrics['max_drawdown'])}` unites
- Plus longue serie de pertes : `{metrics['longest_losing_streak']}`
- Periode couverte : `{metrics['start_date']} -> {metrics['end_date']}`

## CLV

- Paris relies a la closing line : `{clv_coverage_text}`
- Cote moyenne prise : `{format_units(metrics['avg_odds'])}`
- Cote moyenne de cloture : `{format_units(clv_metrics['avg_closing_odds'])}`
- CLV moyen en cote (`opening - closing`) : `{format_units(clv_metrics['avg_clv_odds_diff'])}`
- CLV median en cote : `{format_units(clv_metrics['median_clv_odds_diff'])}`
- CLV moyen en pourcentage de cote : `{format_percent(clv_metrics['avg_clv_odds_ratio'])}`
- Taux de CLV positif : `{format_percent(clv_metrics['positive_clv_rate'])}`
- Delta moyen de proba implicite (`closing - opening`) : `{format_decimal(clv_metrics['avg_clv_probability_diff'])}`
- Delta median de proba implicite : `{format_decimal(clv_metrics['median_clv_probability_diff'])}`

## Verdict

Niveau de preuve actuel : `{verdict.evidence_level}`

Points qui vont dans le bon sens :
{chr(10).join(strength_lines)}

Points qui empechent encore de parler de robustesse forte :
{chr(10).join(risk_lines)}

## Lecture correcte

- Ce rapport ne peut pas prouver mathematiquement que la strategie gagnera dans le futur.
- Il peut seulement mesurer si le signal observe a l'air fragile, moyen ou encourageant.
- Le vrai test propre reste une strategie gelee suivie en live sans retouche.
- Le CLV historique sur `2025/26` sert ici a verifier si les prix pris battaient deja la cloture sur les matchs testes.

## Repartition mensuelle

{chr(10).join(monthly_lines)}

## Repartition par ligue

{chr(10).join(league_lines)}

## Repartition par strategie

{chr(10).join(strategy_lines)}

## Ce qu'il faut faire maintenant

- Geler le portefeuille utilise en live.
- Logger chaque pari recommande avec sa date de generation.
- Continuer a logger la cote de cloture pour prolonger l'audit CLV.
- Evaluer uniquement les matchs joues apres la date de gel.

{next_step}
"""
