"""Verify durable state, seal an append-only update, and publish a GitHub report."""
import hashlib
import json
import os
import sys
from pathlib import Path
from paper_core import Journal, digest, utcnow
from run_paper import ROOT, STATE, check_registration, make_report, write


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory():
    return {p.relative_to(STATE).as_posix(): file_hash(p)
            for p in sorted(STATE.rglob('*')) if p.is_file()
            and '.git' not in p.relative_to(STATE).parts
            and p.name not in {'checkpoint.json', 'collector.lock'}}


def verify():
    registration = check_registration()
    checkpoint = json.loads((STATE/'checkpoint.json').read_text(encoding='utf8'))
    if checkpoint['registration_sha256'] != digest(registration):
        raise ValueError('Persistent state belongs to another experiment')
    if checkpoint['files'] != inventory():
        raise ValueError('Persistent state missing or altered; refusing to reset history')
    journal = Journal(STATE/'journal.sqlite3', registration)
    try:
        events = journal.export()
        if checkpoint['events_sha256'] != digest(events):
            raise ValueError('Journal checkpoint mismatch')
    finally:
        journal.db.close()
    return checkpoint, events


def render_report(report, checkpoint):
    status = report['status']
    rows = [
        '# Nuls Bundesliga + 15 stratégies en observation', '',
        '**Simulation uniquement. La stratégie de production reste inchangée.**', '',
        f"Dernier passage : {status['finished_at_utc']} — **{status['state']}**.",
        f"Décisions figées avant match : {report['forecasts']}. Résultats confirmés : {report['settled_fixtures']}.", '',
        'Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:40, 06:40, 12:40 et 18:40 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.', '',
        '| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for r in report['portfolios']:
        roi = '—' if r['roi'] is None else f"{100*r['roi']:.2f} %"
        rows.append(f"| {r['label']} | {r['settled_bets']} | {r['pending_bets']} | {r['pending_stake']:.2f} | {r['profit']:.2f} | {roi} | {r['max_daily_drawdown']:.2f} | {r['additional_profit']:.2f} |")
    rows += ['',
        'La référence est la stratégie de nuls Bundesliga du backtest, calculée avec les mêmes modèles figés et les mêmes cotes que les ajouts. Ce nouveau suivi commence à zéro ; les gains historiques ne sont pas importés.', '',
        'Les 15 stratégies sont suivies individuellement et avec les nuls Bundesliga, à 1 unité virtuelle par pari. Le portefeuille commun conserve les nuls Bundesliga en priorité puis le premier ajout admissible dans l’ordre figé : une seule issue et une seule mise par match, même si plusieurs stratégies le sélectionnent. Les lignes individuelles ne doivent pas être additionnées. La sélection des 15 repose sur des résultats récents déjà observés ; seule la suite du suivi est prospective.', '',
        'Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.', '',
        'Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.', '',
        '[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-positive15.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Paris uniques, cotes et stratégies](tickets.json) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)', '',
        f"Journal : {checkpoint['event_count']} événements, empreinte `{checkpoint['events_sha256']}`.", '',
        'Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.',
    ]
    return '\n'.join(rows)+'\n'


def seal(prior_events=None, outcome='success'):
    registration = check_registration()
    if not (STATE/'journal.sqlite3').exists():
        raise ValueError('Journal missing')
    journal = Journal(STATE/'journal.sqlite3', registration)
    try:
        events = journal.export()
        if prior_events is not None and events[:len(prior_events)] != prior_events:
            raise ValueError('Earlier journal events changed or disappeared')
        status = json.loads((STATE/'last_run.json').read_text(encoding='utf8'))
        if outcome != 'success':
            status = {'state':'collection_failed', 'finished_at_utc':utcnow().isoformat(),
                      'github_run_id':os.environ.get('GITHUB_RUN_ID'), 'production_changed':False}
        make_report(journal, status)
    finally:
        journal.db.close()
    checkpoint = {'registration_sha256':digest(registration), 'events_sha256':digest(events),
                  'event_count':len(events), 'github_run_id':os.environ.get('GITHUB_RUN_ID'),
                  'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'), 'sealed_at_utc':utcnow().isoformat()}
    report = json.loads((STATE/'report.json').read_text(encoding='utf8'))
    markdown = render_report(report, checkpoint)
    (STATE/'README.md').write_text(markdown, encoding='utf8')
    checkpoint['files'] = inventory()
    write(STATE/'checkpoint.json', checkpoint)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf8') as file:
            file.write(markdown)
    return report['status']['state']


def main():
    # Only GitHub-hosted runs may update the live simulation.
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Live simulation runs on GitHub Actions only')
    prefix = Path(os.environ['RUNNER_TEMP'])/'paper-verified-prefix.json'
    if sys.argv[1] == 'verify':
        checkpoint, events = verify()
        write(prefix, events)
        print(f"Verified {len(events)} persistent events from run {checkpoint.get('github_run_id')}")
    elif sys.argv[1] == 'seal':
        events = json.loads(prefix.read_text(encoding='utf8'))
        state = seal(events, os.environ.get('COLLECT_OUTCOME', 'failure'))
        print('Saved report status:', state)
    elif sys.argv[1] == 'health':
        verify()
        report = json.loads((STATE/'report.json').read_text(encoding='utf8'))
        if report['status']['state'] != 'collected':
            raise ValueError('Simulation needs attention: '+report['status']['state'])
    else:
        raise ValueError('Unknown command')


if __name__ == '__main__':
    main()
