const integer = new Intl.NumberFormat('fr-FR');
const decimal = new Intl.NumberFormat('fr-FR', {minimumFractionDigits:2, maximumFractionDigits:2});
const percent = new Intl.NumberFormat('fr-FR', {style:'percent',minimumFractionDigits:1,maximumFractionDigits:1});
const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const signed = value => value == null ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${decimal.format(Math.abs(value))}`;
const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : '';
const date = value => new Intl.DateTimeFormat('fr-FR',{timeZone:'Europe/Paris',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
const day = value => new Intl.DateTimeFormat('fr-FR',{timeZone:'Europe/Paris',day:'numeric',month:'long',year:'numeric'}).format(new Date(value));
function validMetric(m) {
  return m && Number.isInteger(m.settled) && m.settled >= 0 && Number.isInteger(m.pending) && m.pending >= 0
    && Number.isFinite(m.profit) && (m.roi === null || Number.isFinite(m.roi)) && (m.settled !== 0 || m.roi === null);
}
function validPayload(data) {
  if (data?.schemaVersion !== 1 || !['ready','attention'].includes(data.status) || data.strategies?.length !== 9 || !data.live || !data.history) return false;
  const ids=data.strategies.map(s=>s.id);
  if (new Set(ids).size !== 9 || JSON.stringify(ids)!==JSON.stringify(data.history.nineMembers)) return false;
  for (const period of [data.live,data.history.periods?.season,data.history.periods?.previous]) {
    if (!period || !validMetric(period.union) || !validMetric(period.baseline) || !ids.every(id=>validMetric(period.individual?.[id]))) return false;
  }
  return Array.isArray(data.tickets) && new Set(data.tickets.map(t=>t.fixture_id)).size===data.tickets.length
    && data.tickets.every(t=>t.portfolio==='bundesliga_plus9' && t.stake===1 && Number.isFinite(t.odds) && t.odds>1
      && ['pending','won','lost'].includes(t.status) && (t.status==='pending' ? t.profit===null : Number.isFinite(t.profit)));
}
function cells(m) {
  return `<td>${integer.format(m.settled)}</td><td class="${tone(m.profit)}">${signed(m.profit)} u</td><td class="${tone(m.roi)}">${m.roi===null?'—':percent.format(m.roi)}</td><td>${integer.format(m.pending)}</td>`;
}
function renderPeriod(data,period) {
  const model=period==='live'?data.live:data.history.periods[period];
  const names={live:'Depuis la mise en observation',season:'Saison 2026/27 · simulation',previous:'Saison 2025/26 · simulation'};
  $('#observation-period-title').textContent=names[period];
  $('#observation-period-copy').textContent=period==='live'
    ? `Décisions inscrites avant match depuis le ${date(data.live.registeredAt)}. Les gains historiques sont exclus.`
    : period==='season' ? `Reconstitution du début de saison au ${day(data.history.asOf+'T12:00:00Z')}. Ce bilan est figé à cette date.`
    : 'Reconstitution de la saison 2025/26 avec les versions annuelles des modèles et les mêmes filtres.';
  $('#observation-settled').textContent=integer.format(model.union.settled);
  $('#observation-profit').textContent=`${signed(model.union.profit)} u`;
  $('#observation-profit').className=tone(model.union.profit);
  $('#observation-roi').textContent=model.union.roi===null?'—':percent.format(model.union.roi);
  $('#observation-roi').className=tone(model.union.roi);
  $('#observation-pending').textContent=integer.format(model.union.pending);
  $('#observation-totals').innerHTML=`<tr><td>Nuls Bundesliga seuls</td>${cells(model.baseline)}</tr><tr class="observation-union"><td>Nuls Bundesliga + 9 stratégies</td>${cells(model.union)}</tr>`;
  $('#observation-strategies').innerHTML=data.strategies.map(s=>`<tr><td><span class="observation-code">${escape(s.code)}</span><strong>${escape(s.label)}</strong><small>${escape(s.model)} · seuil ${(s.threshold*100).toFixed(0)} %${s.filter?' · '+escape(s.filter):''}</small></td>${cells(model.individual[s.id])}</tr>`).join('');
  $('#observation-history-note').hidden=period==='live';
  $('#observation-panel').setAttribute('aria-labelledby','tab-'+period);
  document.querySelectorAll('[data-period]').forEach(button=>{
    const active=button.dataset.period===period;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
  });
}
function renderTickets(data,filter) {
  const codes=Object.fromEntries(data.strategies.map(s=>[s.id,s.code]));
  const rows=data.tickets.filter(t=>filter==='all'||(filter==='pending'?t.status==='pending':t.status!=='pending'))
    .sort((a,b)=>new Date(a.kickoff_utc)-new Date(b.kickoff_utc));
  $('#observation-tickets').innerHTML=rows.map(t=>{
    const outcome=t.outcome==='draw'?'Match nul':t.outcome==='home'?t.home_team:t.away_team;
    const names=t.selected_members.map(id=>id==='Bundesliga_anchor'?'Bundesliga':codes[id]).filter(Boolean);
    const status=t.status==='pending'?(new Date(t.kickoff_utc)>Date.now()?'À venir':'Résultat à confirmer'):t.status==='won'?'Gagné':'Perdu';
    return `<tr><td><strong>${escape(t.home_team)} <span>vs</span> ${escape(t.away_team)}</strong><small>${escape(date(t.kickoff_utc))}</small><small>Enregistré le ${escape(date(t.enrolled_at_utc))}</small></td><td>${escape(outcome)}<small>Cote ${decimal.format(t.odds)} · 1 u</small></td><td>${escape(names.join(' · '))}<small>${names.length>1?'Un seul pari retenu':''}</small></td><td class="observation-state ${t.status==='pending'?'':tone(t.profit)}">${status}</td><td class="${tone(t.profit)}">${t.profit===null?'—':signed(t.profit)+' u'}</td></tr>`;
  }).join('');
  $('#observation-empty-tickets').hidden=rows.length!==0;
  document.querySelectorAll('[data-ticket-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.ticketFilter===filter)));
}
async function boot() {
  try {
    const response=await fetch(`./data/observation.json?v=${Date.now()}`,{cache:'no-store'});
    if (!response.ok) throw new Error('Unavailable');
    const data=await response.json();if (!validPayload(data)) throw new Error('Unverified observation');
    const age=Date.now()-Date.parse(data.live.updatedAt);
    $('#observation-updated').textContent=`Dernière collecte : ${date(data.live.updatedAt)}${age>86400000?' · actualisation à vérifier':''}`;
    $('#observation-content').hidden=false;
    if (data.status==='attention') {$('#observation-error').hidden=false;$('#observation-error').textContent='La dernière collecte demande une vérification. Les résultats ci-dessous sont ceux du journal conservé.';}
    renderPeriod(data,'live');renderTickets(data,'all');
    document.querySelectorAll('[data-period]').forEach(button=>{
      button.addEventListener('click',()=>renderPeriod(data,button.dataset.period));
      button.addEventListener('keydown',event=>{
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault();const tabs=[...document.querySelectorAll('[data-period]')];let i=tabs.indexOf(button);
        i=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
        tabs[i].focus();renderPeriod(data,tabs[i].dataset.period);
      });
    });
    document.querySelectorAll('[data-ticket-filter]').forEach(button=>button.addEventListener('click',()=>renderTickets(data,button.dataset.ticketFilter)));
  } catch {
    $('#observation-error').hidden=false;$('#observation-content').hidden=true;
    $('#observation-updated').textContent='Dernière collecte non vérifiée';
  }
}
if (typeof document!=='undefined') boot();
