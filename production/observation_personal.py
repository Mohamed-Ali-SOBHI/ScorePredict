"""Generate a self-contained personal report outside the published website."""
from __future__ import annotations

import argparse
import os
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from production import observation_export as ex

OUTPUT = ex.ROOT.parent / 'suivi_prive_9' / 'mon_suivi.html'


def number(value, *, percent=False, units=False):
    if value is None:
        return '—'
    value = value * 100 if percent else value
    text = (f'{value:+.2f}' if value else '0.00') if units else f'{value:.1f}'
    return text.replace('.', ',') + (' %' if percent else ' u' if units else '')


def date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(
        ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M')


def metric_row(label, metric, *, total=False):
    tag = 'td'
    return (f'<tr{" class=total" if total else ""}><th scope="row">{label}</th>'
            f'<{tag}>{metric["settled"]}</{tag}><{tag}>{number(metric["profit"], units=True)}</{tag}>'
            f'<{tag}>{number(metric["roi"], percent=True)}</{tag}>'
            f'<{tag}>{metric["pending"]}</{tag}></tr>')


def report_table(data, period):
    metrics = data['live'] if period == 'live' else data['history']['periods'][period]
    if metrics is None:
        return '<p role="status">Suivi indisponible : aucun bilan actuel vérifié.</p>'
    rows = [metric_row('Nuls Bundesliga<small>Référence de recherche</small>', metrics['baseline'])]
    for strategy in data['strategies']:
        detail = strategy['model']
        label = (f'{escape(strategy["code"])} · {escape(strategy["label"])}'
                 f'<small>{escape(detail)}</small>')
        rows.append(metric_row(label, metrics['individual'][strategy['id']]))
    rows.append(metric_row('Total avec Bundesliga · sans doublon', metrics['union'], total=True))
    return ('<div class="scroll" tabindex="0" role="region" aria-label="Bilans des stratégies">'
            '<table><thead><tr><th>Stratégie</th><th>Réglés</th><th>Gain net</th>'
            '<th>Rendement</th><th>En attente</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def private_section(data):
    heading='<h2>Italie et Angleterre · observation privée</h2>'
    if not data or data.get('status')!='ready':
        return heading+'<p class="note">La dernière collecte privée ne peut pas être vérifiée.</p>'
    rows=''.join(metric_row(escape(s['code']+' · '+s['label']),s['metrics']) for s in data['strategies'])
    result=(heading+'<p class="note">Anciennes règles du site, suivies séparément depuis le 18/10/2026. '
        +'Ces résultats ne sont pas additionnés au portefeuille des neuf.</p>'
        +'<div class="scroll"><table><thead><tr><th>Stratégie</th><th>Réglés</th><th>Gain net</th>'
        +'<th>Rendement</th><th>En attente</th></tr></thead><tbody>'+rows+'</tbody></table></div>')
    codes={s['id']:s['code'] for s in data['strategies']}
    tickets=[]
    for t in sorted(data['tickets'],key=lambda r:r['date'],reverse=True):
        status={'won':'Gagné','lost':'Perdu','void':'Annulé'}.get(t['status'],'En attente')
        tickets.append('<tr><th>'+escape(t['home']+' – '+t['away'])+'<small>'+escape(date(t['date']))+'</small></th>'
            +'<td>'+escape(codes.get(t['strategy'],t['strategy']))+'</td><td>'+f'{t["odds"]:.2f}'+'</td>'
            +'<td>'+status+'</td><td>'+number(t['profit'],units=True)+'</td></tr>')
    result+='<p class="note">Données du '+escape(date(data['updatedAt']))+' (heure de Paris).</p>'
    if tickets:
        result+='<div class="scroll"><table><thead><tr><th>Match · nul</th><th>Stratégie</th><th>Cote</th><th>Statut</th><th>Gain</th></tr></thead><tbody>'+''.join(tickets)+'</tbody></table></div>'
    return result


def english_section(data):
    heading='<h2>E02 · Angleterre extérieur · filtre strict</h2>'
    if not data or data.get('status')=='unavailable':
        return heading+'<p class="note">La dernière collecte ne peut pas être vérifiée.</p>'
    result=(heading+'<p class="note">Observation privée depuis le '+escape(date(data['registeredAt']))
        +'. Cotes 2 à 6 incluses ; valeur attendue supérieure à 10 % après décote de 2 %. '
        +'1 unité virtuelle par pari. La simulation passée reste séparée.</p>')
    if data['status']=='awaiting_capture':
        result+='<p class="note">En attente de la première collecte après activation. Aucun ancien pari repris.</p>'
    elif data['status']=='attention':
        result+='<p class="notice">Dernière collecte incomplète ; bilan du journal vérifié.</p>'
    result+='<div class="scroll"><table><thead><tr><th>Depuis l’activation</th><th>Réglés</th><th>Gain net</th><th>Rendement</th><th>En attente</th></tr></thead><tbody>'
    result+=metric_row('Angleterre extérieur · E02',data['metrics'])
    result+=metric_row('Nuls Bundesliga<small>Référence publique observée sur les premières captures après activation</small>',data['baseline'])
    result+=metric_row('Total Bundesliga + E02 · sans doublon',data['union'],total=True)
    result+='</tbody></table></div>'
    history=data['history']
    standalone=history['standalone'];combined=history['with_public_bundesliga']
    result+='<details><summary>Simulation du 15 août au 17 octobre · historique séparé</summary><p class="note">Angleterre seule : '+str(standalone['bets'])+' paris, '+number(standalone['profit'],units=True)+', '+number(standalone['roi'],percent=True)+'. Avec les nuls Bundesliga actuels, sans doublons : '+str(combined['bets'])+' paris, '+number(combined['profit'],units=True)+', '+number(combined['roi'],percent=True)+'. Ces paris ne sont pas inclus dans le suivi depuis activation.</p></details>'
    rows=[]
    for ticket in sorted(data['tickets'],key=lambda r:r['date'],reverse=True):
        label={'pending':'En attente','won':'Gagné','lost':'Perdu'}[ticket['status']]
        rows.append('<tr><th>'+escape(ticket['home']+' – '+ticket['away'])+'<small>'+escape(date(ticket['date']))+'</small></th>'
            +'<td>Extérieur</td><td>'+f'{ticket["odds"]:.2f}'+'</td><td>'+label+'</td><td>'+number(ticket['profit'],units=True)+'</td></tr>')
    if rows:
        result+='<div class="scroll"><table><thead><tr><th>Match</th><th>Pari</th><th>Cote</th><th>Statut</th><th>Gain net</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    else:
        result+='<p class="note">Aucun pari E02 enregistré depuis son activation.</p>'
    result+='<p class="note">Source vérifiée du '+escape(date(data['sourceUpdatedAt']))+' (heure de Paris).</p>'
    return result


def render(data,private=None,english=None):
    codes = {s['id']: s['code'] for s in data['strategies']}
    codes['Bundesliga_anchor'] = 'Nuls Bundesliga'
    sections = []
    for period in ['live', 'season', 'previous']:
        hidden = '' if period == 'live' else ' hidden'
        if period == 'live':
            note = ('Paris enregistrés avant match depuis le 18/10/2026.'
                    ' Les paris en attente sont exclus du gain et du rendement.')
        else:
            note = ('Simulation rétrospective ayant servi au choix des stratégies.'
                    ' Elle reste séparée du suivi en observation.')
            if period == 'season':
                note += ' Bilan arrêté au 17/10/2026.'
        sections.append(f'<section data-period="{period}"{hidden}>{report_table(data, period)}'
                        f'<p class="note">{note} Le comparateur Bundesliga est celui de l’étude, avec un modèle différent de celui du site.</p></section>')

    rows = []
    for ticket in sorted(data['tickets'], key=lambda t: (t['kickoff_utc'], t['fixture_id'])):
        status = ticket['status']
        label = {'pending': 'En attente', 'won': 'Gagné', 'lost': 'Perdu'}[status]
        members = ', '.join(codes.get(m, m) for m in ticket['selected_members'])
        outcome = {'home': 'Domicile', 'away': 'Extérieur', 'draw': 'Nul'}[ticket['outcome']]
        rows.append(f'<tr data-status="{status}"><th scope="row">'
                    f'{escape(ticket["home_team"])} – {escape(ticket["away_team"])}'
                    f'<small>{escape(date(ticket["kickoff_utc"]))} · Paris</small></th>'
                    f'<td>{outcome}<small>Cote {ticket["odds"]:.2f}</small></td>'
                    f'<td>{escape(members)}</td><td>{label}</td>'
                    f'<td>{number(ticket["profit"], units=True)}</td></tr>')
    stamp = data['live']['updatedAt'] if data['live'] else data['generatedAt']
    notice = ''
    if data['status'] == 'attention':
        notice = '<p class="notice" role="status">Dernière collecte incomplète. Bilans du journal vérifié ci-dessous.</p>'
    elif data['status'] == 'unavailable':
        notice = '<p class="notice" role="status">Actualisation non vérifiée. Les bilans historiques restent consultables.</p>'
    ticket_area = ('<div class="scroll" tabindex="0" role="region" aria-label="Paris uniques">'
                   '<table><thead><tr><th>Match</th><th>Pari</th><th>Stratégies</th>'
                   '<th>Statut</th><th>Gain net</th></tr></thead>'
                   f'<tbody id="tickets">{"".join(rows)}</tbody></table></div>'
                   '<p id="empty" class="note" hidden>Aucun pari dans cette catégorie.</p>')
    if data['live'] is None:
        ticket_area = '<p>Liste actuelle non vérifiée.</p>'
    return TEMPLATE.replace('@@STAMP@@', escape(date(stamp))).replace(
        '@@NOTICE@@', notice).replace('@@SECTIONS@@', ''.join(sections)).replace(
        '@@TICKETS@@', ticket_area).replace('@@PRIVATE@@',private_section(private)
            +'<section style="margin-top:36px">'+english_section(english)+'</section>')


TEMPLATE = '''<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Mon suivi · stratégies en observation</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f7f8f5;color:#202c26;font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:auto;padding:40px 24px}h1{font-size:30px;letter-spacing:-1px;margin:4px 0}h2{font-size:21px;margin:0}
.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#50655a}.note,small{color:#617068;font-size:12px}small{display:block;font-weight:400;margin-top:3px}
header{margin-bottom:30px}header p{margin:6px 0}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:18px 0 12px}
label{font-size:13px}select{font:inherit;color:inherit;border:1px solid #cad3cc;border-radius:6px;background:white;padding:9px;max-width:100%;cursor:pointer}
select:focus-visible,.scroll:focus-visible{outline:2px solid #197347;outline-offset:3px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:right;background:#fff;font-size:14px}
th,td{padding:13px 12px;border-bottom:1px solid #e5eae4;white-space:nowrap}th:first-child{text-align:left;white-space:normal;min-width:245px}thead th{font-size:12px;color:#617068;font-weight:500}tbody th{font-weight:500}
.total{background:#e8f1e9;font-weight:650}.total th{font-weight:650}.note{margin:12px 0 26px}.notice{border-left:3px solid #98733b;padding:10px 15px;background:#fff8e9}footer{font-size:12px;color:#617068;margin-top:32px}
[hidden]{display:none!important}@media(max-width:600px){main{padding:24px 16px}.toolbar{align-items:flex-start;flex-direction:column;gap:8px}h1{font-size:26px}th,td{padding:11px 9px}th:first-child{min-width:215px}}
</style></head><body><main>
<header><span class="eyebrow">Suivi personnel · fichier local</span><h1>Mes stratégies en observation</h1>
<p class="note">Données du @@STAMP@@ (heure de Paris).<br>Pour actualiser : ouvrir « Actualiser le suivi.cmd ».</p></header>
@@NOTICE@@
<div class="toolbar"><h2>Bilans</h2><label>Période <select id="period">
<option value="live">Depuis la mise en observation</option><option value="season">Saison 2026/27 · simulation</option><option value="previous">Saison 2025/26 · simulation</option>
</select></label></div>
@@SECTIONS@@
<div class="toolbar"><h2>Paris enregistrés</h2><label>Afficher <select id="filter"><option value="pending">En attente</option><option value="settled">Réglés</option><option value="all">Tous</option></select></label></div>
@@TICKETS@@
<section style="margin-top:36px">@@PRIVATE@@</section>
<footer>1 unité virtuelle par pari. Un seul pari par match dans le total : priorité aux nuls Bundesliga, puis à l’ordre figé des stratégies. Les lignes individuelles ne s’additionnent pas.</footer>
</main><script>
const period=document.querySelector('#period');
period.addEventListener('change',()=>document.querySelectorAll('[data-period]').forEach(section=>section.hidden=section.dataset.period!==period.value));
const filter=document.querySelector('#filter');
function filterTickets(){let visible=0;document.querySelectorAll('#tickets tr').forEach(row=>{row.hidden=!(filter.value==='all'||(filter.value==='pending'?row.dataset.status==='pending':row.dataset.status!=='pending'));if(!row.hidden)visible++});const empty=document.querySelector('#empty');if(empty)empty.hidden=visible>0;}
filter.addEventListener('change',filterTickets);filterTickets();
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    ex.require_private_output(args.output)
    data = ex.snapshot()
    from production.private_observation_personal import load_latest
    private = load_latest()
    from production.english_away_export import snapshot as english_snapshot
    english = english_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix('.html.tmp')
    temp.write_text(render(data,private,english), encoding='utf8')
    os.replace(temp, args.output)
    print('Suivi personnel :', args.output, '(' + data['status'] + ')')
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())


if __name__ == '__main__':
    main()
