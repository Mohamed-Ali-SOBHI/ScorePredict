const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));
const clubCrest = team => {
  const crests = window.ScorePredictCrests || {};
  const file = Object.hasOwn(crests, team) ? crests[team] : null;
  return file ? '<img class="club-crest" src="./assets/crests/' + escape(file)
    + '" width="24" height="24" alt="" loading="lazy" decoding="async">' : '';
};
const number = value => value == null || Number.isNaN(Number(value))
  ? '—'
  : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(value);
const dateFormat = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' });
let matches = [];
let activeLeague = '';
let searchQuery = '';
const normalizeSearch = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');

function teamStat(team, key) {
  if (!team) return null;
  if (key === 'played' || key === 'form') return team[key];
  return team.averages ? team.averages[key] : null;
}

function formTokens(value) {
  if (!Array.isArray(value) || !value.length) return '<span class="form-empty">—</span>';
  return value.map(result => {
    const data = {
      w: ['V', 'win', 'Victoire'], d: ['N', 'draw', 'Match nul'], l: ['D', 'loss', 'Défaite']
    }[String(result).toLowerCase()] || ['—', 'unknown', 'Résultat indisponible'];
    return '<span class="form-token ' + data[1] + '" title="' + data[2] + '">' + data[0] + '</span>';
  }).join('');
}

function probabilityCell(value, label) {
  if (value == null || !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 1) return '<td class="probability-cell" data-label="' + label + '"><strong>—</strong></td>';
  const percentage = Number(value) * 100;
  return '<td class="probability-cell" data-label="' + label + '"><strong>' + percentage.toFixed(0)
    + ' %</strong><span class="mini-probability" aria-hidden="true"><i style="width:'
    + percentage.toFixed(2) + '%"></i></span></td>';
}

function detailTable(home, away) {
  const rows = [
    ['Matchs joués', 'played'], ['Forme récente', 'form'], ['Buts marqués / match', 'goals'],
    ['Buts encaissés / match', 'conceded'], ['Occasions créées (xG)', 'xg'],
    ['Occasions concédées (xG)', 'xga'], ['Points attendus / match', 'xpoints']
  ];
  const body = rows.map(([label, key]) => {
    const homeValue = key === 'form' ? formTokens(teamStat(home, key)) : number(teamStat(home, key));
    const awayValue = key === 'form' ? formTokens(teamStat(away, key)) : number(teamStat(away, key));
    return '<tr><th scope="row">' + label + '</th><td>' + homeValue + '</td><td>' + awayValue + '</td></tr>';
  }).join('');
  const homeDate = home && home.asOf ? escape(home.asOf) : 'indisponible';
  const awayDate = away && away.asOf ? escape(away.asOf) : 'indisponible';
  return '<div class="detail-panel"><div class="detail-heading"><strong>Cette saison</strong>'
    + '</div><table class="team-comparison">'
    + '<thead><tr><th scope="col">Cette saison</th><th scope="col">' + escape(home ? home.name : '')
    + '</th><th scope="col">' + escape(away ? away.name : '') + '</th></tr></thead>'
    + '<tbody>' + body + '</tbody></table>'
    + '<p class="detail-note">Derniers matchs disponibles : ' + escape(home ? home.name : '') + ' ' + homeDate
    + ' · ' + escape(away ? away.name : '') + ' ' + awayDate + '</p></div>';
}

function matchRows(match, index) {
  const home = match.teams && match.teams[0] ? match.teams[0] : null;
  const away = match.teams && match.teams[1] ? match.teams[1] : null;
  const matchDate = dateFormat.format(new Date(match.date));
  const detailId = 'match-detail-' + index;
  const row = '<tr class="match-row" style="--row-delay:' + Math.min(index, 8) * 45 + 'ms">'
    + '<td class="league-cell"><span>' + escape(match.leagueLabel) + '</span></td>'
    + '<th class="encounter-cell" scope="row"><span class="mobile-meta">' + escape(match.leagueLabel) + ' · ' + escape(matchDate) + '</span>'
    + '<span class="encounter-name encounter-clubs"><span class="encounter-team">' + clubCrest(match.homeTeam) + '<span>' + escape(match.homeTeam)
    + '</span></span><span class="encounter-team">' + clubCrest(match.awayTeam) + '<span><span class="versus">vs</span> ' + escape(match.awayTeam) + '</span></span></span></th>'
    + '<td class="date-cell"><time datetime="' + escape(match.date) + '">' + escape(matchDate) + '</time></td>'
    + probabilityCell(match.probabilities ? match.probabilities[0] : null, '1')
    + probabilityCell(match.probabilities ? match.probabilities[1] : null, 'N')
    + probabilityCell(match.probabilities ? match.probabilities[2] : null, '2')
    + '<td class="form-cell"><div><span>1</span><span class="form-strip">' + formTokens(teamStat(home, 'form'))
    + '</span></div><div><span>2</span><span class="form-strip">' + formTokens(teamStat(away, 'form')) + '</span></div></td>'
    + '<td class="action-cell"><button class="detail-toggle" type="button" aria-expanded="false" aria-controls="'
    + detailId + '" data-detail="' + detailId + '"><span aria-hidden="true">+</span><span class="sr-only">Comparer '
    + escape(match.homeTeam) + ' et ' + escape(match.awayTeam) + '</span></button></td></tr>';
  const detail = '<tr class="detail-row" id="' + detailId + '" hidden><td colspan="8">' + detailTable(home, away) + '</td></tr>';
  return row + detail;
}

function showLoading() {
  const element = document.getElementById('matches');
  if (element) element.innerHTML = '<div class="loading-state">Chargement des analyses</div>';
}

function render() {
  const matchesElement = document.getElementById('matches');
  if (!matchesElement) return;
  const visible = matches.filter(match => (!activeLeague || match.league === activeLeague)
    && normalizeSearch(match.homeTeam + ' ' + match.awayTeam).includes(normalizeSearch(searchQuery)))
    .sort((left, right) => new Date(left.date) - new Date(right.date));
  document.getElementById('matchCount').textContent = visible.length + ' match' + (visible.length > 1 ? 's' : '')
    + ((activeLeague || searchQuery) ? ' sur ' + matches.length : ' à venir');
  if (!visible.length) {
    matchesElement.innerHTML = '<div class="empty-state"><strong>' + (matches.length ? 'Aucun match trouvé' : 'Aucun match disponible')
      + '</strong><p>' + (matches.length ? 'Essayez une autre équipe ou un autre championnat.' : 'Les prochaines analyses apparaîtront ici.') + '</p></div>';
    return;
  }
  const days = new Map();
  visible.forEach(match => {
    const day = parisDay(match.date);
    if (!days.has(day)) days.set(day, []);
    days.get(day).push(match);
  });
  const dayFormat = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Paris' });
  let rowIndex = 0;
  matchesElement.innerHTML = [...days.values()].map(dayMatches => '<section class="match-day"><h2>'
    + escape(dayFormat.format(new Date(dayMatches[0].date))) + '<span>' + dayMatches.length + '</span></h2>'
    + '<div class="match-table-wrap"><table class="match-table"><thead><tr>'
    + '<th scope="col">Championnat</th><th scope="col">Rencontre</th><th scope="col">Heure</th>'
    + '<th scope="col" title="Victoire à domicile">1</th><th scope="col" title="Match nul">N</th>'
    + '<th scope="col" title="Victoire à l’extérieur">2</th><th scope="col">Forme</th>'
    + '<th scope="col"><span class="sr-only">Statistiques</span></th></tr></thead><tbody>'
    + dayMatches.map(match => matchRows(match, rowIndex++)).join('') + '</tbody></table></div></section>').join('');

}

function parisDay(value) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(new Date(value));
}

async function load() {
  try {
    showLoading();
    const response = await fetch('./data/explorer.json?t=' + Date.now(), { cache: 'no-store' });
    if (!response.ok) throw new Error('Chargement impossible');
    const data = await response.json();
    const age = Date.now() - new Date(data.meta ? data.meta.latestPredictionAt : 0).getTime();
    const now = Date.now();
    const end = now + 86400000;
    if (data.meta && data.meta.status !== 'blocked' && age >= 0 && age < 86400000 && data.explorer) {
      matches = data.explorer.matches.filter(match => (
        new Date(match.date).getTime() > now && new Date(match.date).getTime() < end
      ));
    } else {
      matches = [];
    }
    const leagueFilters = document.getElementById('leagueFilters');
    if (leagueFilters) {
      const leagueMap = {};
      matches.forEach(match => { leagueMap[match.league] = match.leagueLabel; });
      Object.entries(leagueMap).sort((left, right) => left[1].localeCompare(right[1], 'fr'))
        .forEach(([value, label]) => {
          const button = document.createElement('button');
          button.className = 'league-filter-button';
          button.type = 'button';
          button.dataset.league = value;
          button.setAttribute('aria-pressed', 'false');
          button.textContent = label;
          leagueFilters.appendChild(button);
        });
    }
    render();
  } catch (error) {
    console.error('Explorer load error:', error);
    const matchesElement = document.getElementById('matches');
    if (matchesElement) matchesElement.innerHTML = '<div class="empty-state"><strong>Chargement impossible</strong>'
      + '<p>Les analyses seront affichées dès la prochaine mise à jour</p></div>';
  }
}

document.addEventListener('click', event => {
  const leagueButton = event.target.closest('.league-filter-button');
  if (leagueButton) {
    activeLeague = leagueButton.dataset.league || '';
    document.querySelectorAll('.league-filter-button').forEach(button => {
      const isActive = button === leagueButton;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    });
    render();
    return;
  }
  const button = event.target.closest('.detail-toggle');
  if (!button) return;
  const detail = document.getElementById(button.dataset.detail);
  if (!detail) return;
  const willOpen = detail.hidden;
  detail.hidden = !willOpen;
  button.setAttribute('aria-expanded', String(willOpen));
  const icon = button.querySelector('[aria-hidden="true"]');
  if (icon) icon.textContent = willOpen ? '×' : '+';
});

document.getElementById('matchSearch').addEventListener('input', event => {
  searchQuery = event.target.value.trim();
  render();
});

document.addEventListener('error', event => {
  if (event.target.matches('.club-crest')) event.target.hidden = true;
}, true);
load();
