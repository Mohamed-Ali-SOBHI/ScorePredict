const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => value == null ? '—' : new Intl.NumberFormat('fr-FR',{maximumFractionDigits:2}).format(value);
const dateFormat = new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Paris'});
const form = value => value.map(v => ({w:'V',d:'N',l:'D'}[v])).join(' · ') || '—';
let matches = [];
function render() {
  const league = document.querySelector('#league').value;
  const visible = matches.filter(m => !league || m.league === league);
  document.querySelector('#coverage').textContent = `${visible.length} rencontre${visible.length > 1 ? 's' : ''} analysée${visible.length > 1 ? 's' : ''}`;
  document.querySelector('#matches').innerHTML = visible.length ? visible.map(m => {
    const rows = [['Matchs joués',t=>t.played],['Forme récente (V / N / D)',t=>form(t.form)],['Buts marqués / match',t=>t.averages.goals],['Buts encaissés / match',t=>t.averages.conceded],['Buts attendus / match',t=>t.averages.xg],['Buts attendus adverses / match',t=>t.averages.xga],['Tirs / match',t=>t.averages.shots],['Points attendus / match',t=>t.averages.xpoints]];
    return `<article class="analysis"><header><span>${escape(m.leagueLabel)}</span><time datetime="${escape(m.date)}">${escape(dateFormat.format(new Date(m.date)))}</time></header><h2>${escape(m.homeTeam)} — ${escape(m.awayTeam)}</h2><div class="probabilities">${m.probabilities.map((p,i)=>`<div><label>${['Domicile','Match nul','Extérieur'][i]} <strong>${number(p*100)} %</strong></label><meter min="0" max="1" value="${p}" aria-label="${['Victoire domicile','Match nul','Victoire extérieur'][i]}"></meter></div>`).join('')}</div><details><summary>Comparer les équipes</summary><table class="team-comparison"><thead><tr><th scope="col">Cette saison</th>${m.teams.map(t=>`<th scope="col">${escape(t.name)}</th>`).join('')}</tr></thead><tbody>${rows.map(([label,get])=>`<tr><th scope="row">${label}</th>${m.teams.map(t=>{const v=get(t);return `<td>${typeof v==='string'?escape(v):number(v)}</td>`;}).join('')}</tr>`).join('')}</tbody></table><p class="explorer-note">V : victoire · N : nul · D : défaite · — : donnée indisponible<br>Derniers matchs disponibles : ${m.teams.map(t=>`${escape(t.name)} ${escape(t.asOf || 'indisponible')}`).join(' / ')}</p></details></article>`;
  }).join('') : '<p>Aucune analyse récente disponible dans cette fenêtre</p>';
}
async function load() {
  try {
    const response = await fetch(`./data/explorer.json?t=${Date.now()}`,{cache:'no-store'});
    if (!response.ok) throw new Error('Chargement impossible');
    const data = await response.json();
    const age = Date.now()-new Date(data.meta?.latestPredictionAt).getTime();
    const day = value => new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
    const end = new Date(`${day(Date.now())}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate()+3);
    matches = data.meta?.status !== 'blocked' && age >= 0 && age < 86400000 ? (data.explorer?.matches || []).filter(m=>new Date(m.date).getTime()>Date.now() && day(m.date)<end.toISOString().slice(0,10)) : [];
    for (const [value,label] of new Map(matches.map(m=>[m.league,m.leagueLabel]))) document.querySelector('#league').add(new Option(label,value));
    render();
  } catch { document.querySelector('#coverage').textContent='Les analyses ne sont pas disponibles pour le moment'; }
}
document.querySelector('#league').addEventListener('change',render);
load();
