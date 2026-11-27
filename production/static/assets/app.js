const TEAM_CRESTS = window.ScorePredictCrests || {};

document.documentElement.classList.add("js");

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const integer = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const decimalOne = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });
const MATCH_TIMEZONE = "Europe/Paris";

function setText(selector, value, root = document) {
  const element = $(selector, root);
  if (element) element.textContent = value;
}

function numberOrNull(value) {
  if (value === null || value === "" || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function publicationIsFresh(value) {
  const published = new Date(value).getTime();
  if (!Number.isFinite(published)) return false;
  const age = Date.now() - published;
  return age >= -10 * 60 * 1000 && age <= 24 * 60 * 60 * 1000;
}

function futurePublishedPredictions(data, now = Date.now()) {
  return data.predictions.filter(row => visibleUpcoming(row, now));
}

function visibleUpcoming(row, now = Date.now()) {
  const kickoff = new Date(row.date).getTime();
  const days = row.earlyPublished === true ? 5 : 1;
  return row.historicalOnly !== true && kickoff > now && kickoff < now + days * 86400000;
}

function parisDay(value) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: MATCH_TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function matchCards(data, now = Date.now()) {
  const key = row => [row.league, row.homeTeam, row.awayTeam, parisDay(row.date)].join('|');
  const cards = new Map(futurePublishedPredictions(data, now).map(row => [key(row), row]));
  for (const pick of data.greekDrawStudy || []) {
    const kickoff = Date.parse(pick.date);
    const recorded = Date.parse(pick.recordedAt);
    if (!(recorded <= now && recorded < kickoff)) continue;
    const started = kickoff <= now;
    if (started ? parisDay(kickoff) !== parisDay(now) : !visibleUpcoming(pick, now)) continue;
    const row = {...pick, league:"G1", leagueLabel:"Super League grecque · Étude", outcomeLabel:"Match nul",
      publicStrategyLabel:"Grèce · match nul", research:true, started};
    if (!cards.has(key(row))) cards.set(key(row), row);
  }
  // The ledger takes over after kickoff, even when the daily export no longer has the prediction.
  for (const row of [...data.predictions, ...(data.activity || [])]) {
    const kickoff = new Date(row.date).getTime();
    if (row.recommended !== true || row.historicalOnly === true || !Number.isFinite(kickoff) || kickoff > now) continue;
    const previous = cards.get(key(row));
    if (previous && terminalResult(previous) && !terminalResult(row)) continue;
    cards.set(key(row), {...previous, ...row, started: true});
  }
  return [...cards.values()].filter(row => !terminalResult(row) || parisDay(row.date) === parisDay(now))
    .sort((a,b) => new Date(a.date)-new Date(b.date));
}

function validText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function formatDate(value, withTime = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "numeric",
    month: "long",
    timeZone: MATCH_TIMEZONE,
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function formatFullDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: MATCH_TIMEZONE }).format(date);
}

function formatChartDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", year: "numeric", timeZone: MATCH_TIMEZONE }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}

function signed(value, formatter = decimal) {
  const number = numberOrNull(value);
  if (number === null) return "—";
  if (number > 0) return `+${formatter.format(number)}`;
  if (number < 0) return `−${formatter.format(Math.abs(number))}`;
  return formatter.format(0);
}

function isValidPrediction(prediction) {
  if (!prediction || prediction.recommended !== true) return false;
  const odds = numberOrNull(prediction.odds);
  const probability = numberOrNull(prediction.modelProbability);
  const stake = numberOrNull(prediction.stakeEur);
  const date = new Date(prediction.date);

  return validText(prediction.homeTeam)
    && validText(prediction.awayTeam)
    && validText(prediction.outcomeLabel)
    && !Number.isNaN(date.getTime())
    && odds !== null && odds > 1
    && probability !== null && probability > 0 && probability <= 1
    && stake !== null && stake > 0;
}

function isValidPayload(data) {
  if (!data?.meta || !data?.summary || !Array.isArray(data.predictions)) return false;
  const upcoming = numberOrNull(data.summary.upcomingBets);
  const examined = numberOrNull(data.summary.scoredFixtures);
  return Number.isInteger(upcoming) && upcoming >= 0
    && Number.isInteger(examined) && examined >= 0
    && data.predictions.length === upcoming
    && data.predictions.every(isValidPrediction);
}

async function fetchDashboard() {
  const githubPages = window.location.hostname.endsWith(".github.io");
  if (!githubPages) {
    try {
      const response = await fetch("/api/v1/dashboard", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (response.ok && (response.headers.get("content-type") || "").includes("application/json")) {
        const data = await response.json();
        if (isValidPayload(data)) return data;
      }
    } catch {
      // Le snapshot statique prend le relais lorsque l'API locale n'est pas lancée.
    }
  }

  const response = await fetch(`./data/dashboard.json?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Snapshot indisponible");
  const data = await response.json();
  if (!isValidPayload(data)) throw new Error("Publication incomplète");
  return data;
}

function crestMarkup(team, featured = false, compact = false) {
  const file = Object.hasOwn(TEAM_CRESTS, team) ? TEAM_CRESTS[team] : null;
  // Keep the team name visible even when no crest is available.
  return file ? `<img class="${compact ? "club-crest" : "team-crest"}" src="./assets/crests/${escapeHtml(file)}" width="${compact ? 24 : 64}" height="${compact ? 24 : 64}" alt="" decoding="async" loading="${featured ? "eager" : "lazy"}">` : "";
}

function matchesStrategy(row, rule) {
  const outcome = row.outcome || ({"Match nul":"draw", "Victoire extérieure":"away_win", "Victoire domicile":"home_win", "Victoire à domicile":"home_win"})[row.outcomeLabel];
  return row.league === rule.league && outcome === rule.outcome
    && (!rule.id || row.strategy === rule.id)
    && !(rule.excludeStrategyIds || []).includes(row.strategy);
}

function featuredMatches(rows, now = Date.now()) {
  const sorted = [...rows].sort((a,b) => new Date(a.date)-new Date(b.date));
  const next = sorted.find(row => !terminalResult(row) && new Date(row.date).getTime() > now);
  return (next ? [next, ...sorted.filter(row => row !== next)] : sorted)
    .map(row => ({...row, featured:row === next}));
}

function predictionMarkup(prediction) {
  return compactMatchMarkup(prediction);
}

function followedMatchMarkup(match) {
  return compactMatchMarkup(match);
}

function compactMatchMarkup(match) {
  const league = match.leagueLabel || match.league || "Championnat";
  const odds = numberOrNull(match.odds);
  const probability = numberOrNull(match.modelProbability);
  const confirmed = terminalResult(match);
  const status = match.started || confirmed ? resultLabel(match.status, match.date) : "À venir";
  const score = confirmed && match.status !== "void" && match.actualScore ? match.actualScore : "";
  const key = match.id || [match.league, match.date, match.homeTeam, match.awayTeam].join("|");
  const clock = new Intl.DateTimeFormat("fr-FR", {hour:"2-digit", minute:"2-digit", timeZone:MATCH_TIMEZONE}).format(new Date(match.date));
  const day = new Intl.DateTimeFormat("fr-FR", {day:"numeric", month:"short", timeZone:MATCH_TIMEZONE}).format(new Date(match.date));
  const tone = match.status === "won" ? "won" : match.status === "lost" ? "lost" : "";
  return `<details class="pick-row${match.featured ? " pick-featured" : ""}" data-pick-key="${escapeHtml(key)}">
    <summary class="pick-summary">
      ${match.featured ? '<span class="next-match-label">Prochain match</span>' : ""}
      <time class="pick-time" datetime="${escapeHtml(match.date)}"><strong>${escapeHtml(clock)}</strong><span>${escapeHtml(day)}</span></time>
      <span class="pick-match"><span class="pick-league">${escapeHtml(league)}</span><span class="pick-teams"><span class="pick-team">${crestMarkup(match.homeTeam, match.featured)}<strong>${escapeHtml(match.homeTeam)}</strong></span><span class="versus">vs</span><span class="pick-team">${crestMarkup(match.awayTeam, match.featured)}<strong>${escapeHtml(match.awayTeam)}</strong></span></span></span>
      <span class="prediction-choice"><small>Choix</small><strong>${escapeHtml(match.outcomeLabel)}</strong></span>
      <span class="pick-odds"><small>Cote</small><strong>${odds === null ? "—" : decimal.format(odds)}</strong></span>
      <span class="pick-status ${tone}">${score ? `<strong>${escapeHtml(score)}</strong>` : ""}<span>${escapeHtml(status)}</span></span>
      <span class="pick-expand" aria-hidden="true">+</span><span class="sr-only">Détails du pari</span>
    </summary>
    <dl class="pick-details">
      <div><dt>Stratégie</dt><dd>${escapeHtml(match.publicStrategyLabel || "Stratégie publiée")}</dd></div>
      <div><dt>Indice du modèle</dt><dd>${probability === null ? "—" : percent.format(probability)}</dd></div>
      <div><dt>Mise de référence</dt><dd>1 unité</dd></div>
    </dl>
  </details>`;
}

function resetNoPickCopy(data) {
  const examined = numberOrNull(data?.summary?.scoredFixtures);
  setText(".no-pick-kicker", "Analyse terminée");
  setText(".no-pick-label", "0 match retenu");
  setText(".no-pick-copy", examined === 0
    ? "Aucun match à analyser dans les prochaines 24 heures."
    : examined === null
      ? "Aucune rencontre n'a validé tous les critères."
      : `${integer.format(examined)} ${examined === 1 ? "match analysé" : "matchs analysés"}. Aucun ne remplit tous les critères.`);
  $("#no-pick")?.classList.remove("error-state");
}

function renderPredictions(data) {
  try {
    const predictions = featuredMatches(data.predictions).map(prediction => {
      const strategy = (data.meta?.publicStrategies || []).find(rule =>
        matchesStrategy(prediction, rule));
    return {...prediction, publicStrategyLabel: strategy?.label || prediction.publicStrategyLabel};
    });
    setText("#pick-count", `${integer.format(predictions.length)} ${predictions.length === 1 ? "match" : "matchs"}`);
    const holder = $("#pick-list");
    const hasPredictions = predictions.length > 0;
    holder.hidden = !hasPredictions;
    $("#no-pick").hidden = hasPredictions;
    resetNoPickCopy(data);
    const awaitingResult = (data.activity || []).some(row => row.recommended === true && row.historicalOnly !== true && !terminalResult(row) && new Date(row.date).getTime() <= Date.now());
    if (!hasPredictions && awaitingResult) {
      setText(".no-pick-kicker", "Le suivi continue");
      setText(".no-pick-label", "Aucun autre pari à venir");
      setText(".no-pick-copy", "Les rencontres déjà commencées restent dans les résultats ci-dessous");
    }
    const markup = predictions.map((prediction) => predictionMarkup(prediction)).join("");
    if (holder.dataset.markup !== markup) {
      const openKeys = new Set([...holder.querySelectorAll("details[open]")].map(row => row.dataset.pickKey));
      const focusedKey = document.activeElement?.closest(".pick-row")?.dataset.pickKey;
      holder.innerHTML = markup;
      holder.querySelectorAll(".pick-row").forEach(row => {
        row.open = openKeys.has(row.dataset.pickKey);
        if (row.dataset.pickKey === focusedKey) row.querySelector("summary")?.focus();
      });
      holder.dataset.markup = markup;
    }
    $(".today-grid")?.classList.toggle("has-many", predictions.length > 1);
  } catch (e) {
    console.error("renderPredictions error:", e);
  }
}

function resultLabel(status, kickoffAt) {
  if (status === "won") return "Gagné";
  if (status === "lost") return "Perdu";
  if (status === "void") return "Annulé";
  const kickoff = new Date(kickoffAt).getTime();
  if (Number.isFinite(kickoff) && kickoff > Date.now()) return "À venir";
  if (status === "pending_data_refresh") return "Résultat à confirmer";
  if (status === "unmatched") return "Résultat à vérifier";
  return "Résultat en attente";
}

let historyRows = [];
let historyFilter = "all";
let historyLimit = 8;
const terminalResult = (row) => ["won", "lost", "void"].includes(row.status);

function resultMarkup(row, index = 0) {
  const league = row.leagueLabel || row.league || "Championnat";
  const choice = row.outcomeLabel || "Choix publié";
  const odds = numberOrNull(row.odds);
  const stake = numberOrNull(row.stakeEur);
  const model = numberOrNull(row.modelProbability);
  const profit = numberOrNull(row.profitUnits);
  const detailId = `history-detail-${index}`;
  return `<tr class="result-row">
    <td class="league-cell"><span>${escapeHtml(league)}</span></td>
    <th class="encounter-cell" scope="row"><span class="mobile-meta">${escapeHtml(league)} · ${escapeHtml(formatDate(row.date, true))}</span><span class="encounter-name encounter-clubs"><span class="encounter-team">${crestMarkup(row.homeTeam, false, true)}<span>${escapeHtml(row.homeTeam)}</span></span><span class="encounter-team">${crestMarkup(row.awayTeam, false, true)}<span><span class="versus">vs</span> ${escapeHtml(row.awayTeam)}</span></span></span><span class="mobile-choice">${escapeHtml(choice)}${row.historicalOnly ? ' · ancien pari publié' : ''}</span></th>
    <td class="date-cell"><time datetime="${escapeHtml(row.date || "")}">${escapeHtml(formatDate(row.date, true))}</time></td>
    <td class="choice-cell">${escapeHtml(choice)}${row.historicalOnly ? '<br><small>Ancien pari publié</small>' : ''}</td>
    <td class="odds-cell">${odds === null ? "—" : decimal.format(odds)}</td>
    <td class="verdict-cell"><div class="result-verdict">${row.actualScore ? `<strong class="final-score">${escapeHtml(row.actualScore)}</strong>` : ""}<b class="${row.status === "won" ? "won" : row.status === "lost" ? "lost" : ""}">${escapeHtml(resultLabel(row.status, row.date))}</b></div></td>
    <td class="action-cell"><button class="detail-toggle" type="button" aria-expanded="false" aria-controls="${detailId}" data-history-detail="${detailId}"><span aria-hidden="true">+</span><span class="sr-only">Détails du pari ${escapeHtml(row.homeTeam)} contre ${escapeHtml(row.awayTeam)}</span></button></td>
  </tr><tr class="detail-row" id="${detailId}" hidden><td colspan="7"><div class="detail-panel"><div class="detail-heading"><strong>Décision publiée</strong><span>${escapeHtml(choice)}</span></div><dl class="published-details">
    <div><dt>Cote publiée</dt><dd>${odds === null ? "—" : decimal.format(odds)}</dd></div>
    <div><dt>Indice du modèle</dt><dd>${model === null ? "—" : percent.format(model)}</dd></div>
    <div><dt>Mise de référence</dt><dd>1 unité</dd></div>
    <div><dt>Résultat en mises</dt><dd>${terminalResult(row) && profit !== null ? signed(profit) : "—"}</dd></div>
  </dl></div></td></tr>`;
}

function renderHistory() {
  const visible = historyRows.filter(row => historyFilter === "all" || (historyFilter === "settled" ? terminalResult(row) : !terminalResult(row) && new Date(row.date).getTime() > Date.now()));
  let month = '';
  const tableHead = '<div class="match-table-wrap"><table class="match-table dashboard-history-table"><thead><tr><th scope="col">Championnat</th><th scope="col">Rencontre</th><th scope="col">Coup d’envoi</th><th scope="col">Choix publié</th><th scope="col">Cote</th><th scope="col">Résultat</th><th scope="col"><span class="sr-only">Détails du pari</span></th></tr></thead><tbody>';
  const tableEnd = '</tbody></table></div>';
  const markup = visible.slice(0, historyLimit).map((row, index) => {
    const date = new Date(row.date);
    const label = Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('fr-FR', {month:'long',year:'numeric',timeZone:MATCH_TIMEZONE}).format(date) : 'Date à confirmer';
    const heading = label !== month ? `${month ? tableEnd : ''}<h3 class="history-month">${escapeHtml(label)}</h3>${tableHead}` : '';
    month = label;
    return heading + resultMarkup(row, index);
  }).join('') + (month ? tableEnd : '');
  $("#result-list").innerHTML = markup || '<p class="empty-results">Aucune décision dans cette catégorie pour le moment.</p>';
  $("#history-more").hidden = visible.length <= historyLimit;
}

$("#history-more")?.addEventListener('click', () => { historyLimit += 8; renderHistory(); });

$("#result-list")?.addEventListener('click', event => {
  const button = event.target.closest('[data-history-detail]');
  if (!button) return;
  const detail = document.getElementById(button.dataset.historyDetail);
  if (!detail) return;
  const willOpen = detail.hidden;
  detail.hidden = !willOpen;
  button.setAttribute('aria-expanded', String(willOpen));
  button.querySelector('[aria-hidden="true"]').textContent = willOpen ? '×' : '+';
});

document.querySelectorAll("[data-history-filter]").forEach(button => button.addEventListener("click", () => {
  historyFilter = button.dataset.historyFilter;
  historyLimit = 8;
  document.querySelectorAll("[data-history-filter]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  renderHistory();
}));

function liveRoiPoints(rows, verified, expectedRoi) {
  const settled = rows.filter(row => row.recommended === true && ['won','lost'].includes(row.status))
    .sort((a,b) => new Date(a.date)-new Date(b.date));
  if (verified < 5 || settled.length !== verified || settled.some(row => numberOrNull(row.profitUnits) === null || !Number.isFinite(new Date(row.date).getTime()))) return [];
  let profit = 0;
  const points = settled.map((row,i) => ({...row, roi: (profit += Number(row.profitUnits)) / (i+1) * 100}));
  if (numberOrNull(expectedRoi) === null || Math.abs(points.at(-1).roi - expectedRoi*100) > .01) return [];
  return points;
}

function renderTracking(data) {
  try {
    const tracking = data.tracking || {};
    const performanceLive = data.performance?.live || {};
    const allRows = (Array.isArray(data.activity) ? data.activity : []).filter(row => row?.recommended === true && row.historicalOnly !== true);
    const now = Date.now();
    const pending = allRows.filter(row => !terminalResult(row) && visibleUpcoming(row, now)).length;
    const verified = numberOrNull(tracking.verified) ?? numberOrNull(performanceLive.settledBets) ?? 0;
    const won = numberOrNull(tracking.won) ?? 0;
    const lost = numberOrNull(tracking.lost) ?? 0;
    setText("#tracking-pending", integer.format(pending));
    setText("#tracking-verified", integer.format(verified));
    setText("#tracking-won", integer.format(won));
    setText("#tracking-lost", integer.format(lost));
    const liveReturnBlock = $("#live-return-block");
    liveReturnBlock?.classList.remove("calculated", "negative");
    if (verified > 0) {
      const profit = numberOrNull(performanceLive.profitUnits) ?? numberOrNull(data.summary.liveProfitUnits);
      const returnForHundred = numberOrNull(performanceLive["roi"]) ?? numberOrNull(data.summary.liveReturn);
      const returnPercent = returnForHundred === null ? null : returnForHundred * 100;
      setText("#live-return", returnPercent === null ? "Rendement non calculable" : `${signed(returnPercent, decimalOne)} %`);
      setText(
        "#live-return-copy",
        profit === null
          ? `Calculé après ${integer.format(verified)} pari${verified > 1 ? "s" : ""} terminé${verified > 1 ? "s" : ""}`
          : `Soit ${signed(profit)} ${Math.abs(profit) === 1 ? "mise" : "mises"} après ${integer.format(verified)} pari${verified > 1 ? "s" : ""} terminé${verified > 1 ? "s" : ""}`,
      );
      liveReturnBlock?.classList.add("calculated");
      if ((returnPercent ?? profit) < 0) liveReturnBlock?.classList.add("negative");
    } else {
      setText("#live-return", "—");
      setText("#live-return-copy", "Pas encore assez de résultats pour calculer le rendement réel");
    }
    historyRows = allRows.filter(row => new Date(row.date).getTime() <= now || visibleUpcoming(row, now))
      .sort((a, b) => new Date(b.date) - new Date(a.date));
    renderHistory();
  } catch (e) {
    console.error("renderTracking error:", e);
  }
}

function dailyBalances(rows) {
  if (!Array.isArray(rows)) return [];
  const days = [];
  const sorted = rows.filter(row => row?.date && Number.isFinite(Date.parse(row.date)) && numberOrNull(row.value) !== null)
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
  for (const row of sorted) {
    const day = parisDay(row.date);
    if (days.at(-1)?.day !== day) {
      days.push({day, timestamp: Date.parse(day + "T12:00:00Z"), count: 0, opening: days.at(-1)?.value ?? 0});
    }
    const close = days.at(-1);
    close.count++;
    close.value = Number(row.value);
  }
  return days;
}

function balanceTicks(values) {
  const low = Math.min(0, ...values), high = Math.max(0, ...values);
  if (low === high) return [-1, 0, 1];
  const target = (high - low) / 5;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].find(n => n * magnitude >= target) * magnitude;
  const first = Math.floor(low / step), last = Math.ceil(high / step);
  return Array.from({length: last - first + 1}, (_, i) => Number(((first + i) * step).toPrecision(12)));
}

function scaleLinear(value, domainMin, domainMax, rangeMin, rangeMax) {
  if (domainMax === domainMin) return (rangeMin + rangeMax) / 2;
  return rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
}

let displayedChartRows = [];
let balanceRenderKey;

function renderCumulativeChart(rows) {
  const svg = $("#cumulative-chart");
  const tooltip = $("#cumulative-tooltip");
  if (!svg || !tooltip) return;
  const wrap = svg.parentElement;
  const width = Math.max(200, Math.round(wrap.clientWidth || 960));
  const days = dailyBalances(rows);
  const key = width + JSON.stringify(days);
  if (key === balanceRenderKey) return;
  balanceRenderKey = key;
  const compact = width < 600;
  const height = compact ? 222 : 266;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  tooltip.hidden = true;
  wrap.classList.remove("is-hovered");
  if (!days.length) {
    setText("#balance-period", "");
    svg.innerHTML = `<text x="${width/2}" y="${height/2}" text-anchor="middle" class="chart-axis">Aucun résultat cumulé disponible.</text>`;
    return;
  }

  const dayLabel = new Intl.DateTimeFormat("fr-FR", {day:"numeric", month:"short", timeZone:MATCH_TIMEZONE});
  const first = days[0], last = days.at(-1);
  const period = new Intl.DateTimeFormat("fr-FR", {day:"numeric", month:"short", year:"numeric", timeZone:MATCH_TIMEZONE});
  setText("#balance-period", period.formatRange(first.timestamp, last.timestamp));
  const ticks = balanceTicks(days.map(day => day.value));
  const label = signed(last.value) + " u";
  const pillWidth = Math.max(56, label.length * 7.4 + 16);
  const axisNumber = new Intl.NumberFormat("fr-FR", {maximumFractionDigits: 6});
  const left = Math.max(30, ...ticks.map(t => signed(t, axisNumber).length * 7 + 14));
  const right = width - pillWidth - 15;
  const top = 22, bottom = height - 33;
  const y = value => scaleLinear(value, ticks[0], ticks.at(-1), bottom, top);
  const x = stamp => scaleLinear(stamp, first.timestamp, last.timestamp, left + 6, right);
  const points = days.map(day => ({...day, x:x(day.timestamp), y:y(day.value)}));
  const end = points.at(-1);
  const baseline = y(0);
  const line = `M${left},${baseline} ` + points.map(p => `H${p.x} V${p.y}`).join(" ");
  const grid = ticks.map(tick => `<line class="${tick === 0 ? "chart-zero" : "chart-grid"}" x1="${left}" x2="${right}" y1="${y(tick)}" y2="${y(tick)}"/>
    <text class="chart-axis" x="${left-9}" y="${y(tick)+4}" text-anchor="end">${signed(tick, axisNumber)}</text>`).join("");
  const dateTicks = [points[0]];
  const gap = Math.max(65, (right-left) / (compact ? 3 : 6));
  for (const p of points.slice(1,-1)) {
    if (p.x-dateTicks.at(-1).x >= gap && end.x-p.x >= gap) dateTicks.push(p);
  }
  if (points.length > 1) dateTicks.push(end);
  const dates = dateTicks.map((p,i) => {
    const anchor = dateTicks.length === 1 ? "middle" : i === 0 ? "start" : p === end ? "end" : "middle";
    return `<text class="chart-axis" x="${p.x}" y="${height-10}" text-anchor="${anchor}">${dayLabel.format(p.timestamp)}</text>`;
  }).join("");
  const dots = points.length <= 32 ? points.slice(0,-1).map(p =>
    `<circle class="balance-close" cx="${p.x}" cy="${p.y}" r="2.4"/>`).join("") : "";

  svg.innerHTML = `
    <title>Gain cumulé en unités</title>
    <desc>Solde après les paris réglés de chaque journée de match. Dernier cumul : ${label}.</desc>
    <defs><linearGradient id="history-area" gradientUnits="userSpaceOnUse" x1="0" x2="0" y1="${top}" y2="${bottom}">
      <stop stop-color="#16805a" stop-opacity=".16"/><stop offset="1" stop-color="#16805a" stop-opacity=".045"/>
    </linearGradient></defs>
    ${grid}${dates}
    <path class="chart-area" d="${line} V${baseline} Z"/>
    <path class="chart-line" d="${line}"/>${dots}
    <line class="chart-focus-line" y1="${top}" y2="${bottom}"/>
    <circle class="chart-end" cx="${end.x}" cy="${end.y}" r="4.3"/>
    <g class="balance-end-label" aria-hidden="true">
      <rect x="${end.x+9}" y="${end.y-12}" width="${pillWidth}" height="24" rx="6"/>
      <text x="${end.x+9+pillWidth/2}" y="${end.y+4}" text-anchor="middle">${label}</text>
    </g>
    <circle class="chart-focus-dot" r="4.5"/>
    <rect class="chart-hit" x="${left}" y="${top-6}" width="${right-left+5}" height="${bottom-top+12}"
      tabindex="0" role="slider" aria-label="Journée de match" aria-valuemin="1" aria-valuemax="${points.length}"
      aria-valuenow="${points.length}" aria-valuetext="${formatChartDate(end.timestamp)}, cumul ${label}"/>
  `;
  const hit = $(".chart-hit", svg);
  const focusLine = $(".chart-focus-line", svg);
  const focusDot = $(".chart-focus-dot", svg);
  let index = points.length-1;
  function show(i) {
    index = i;
    const p = points[i];
    focusLine.setAttribute("x1", p.x);
    focusLine.setAttribute("x2", p.x);
    focusDot.setAttribute("cx", p.x);
    focusDot.setAttribute("cy", p.y);
    const stamp = formatChartDate(p.timestamp);
    const change = signed(Math.round((p.value-p.opening)*100)/100);
    const count = p.count + " pari" + (p.count > 1 ? "s" : "");
    tooltip.innerHTML = `<span>${stamp} · ${count}</span><strong>${signed(p.value)} u cumulées</strong><span>Sur la journée · ${change} u</span>`;
    tooltip.hidden = false;
    const half = tooltip.offsetWidth/2;
    tooltip.style.left = Math.max(half, Math.min(width-half,p.x))+"px";
    tooltip.style.top = Math.max(tooltip.offsetHeight+14, p.y)+"px";
    wrap.classList.add("is-hovered");
    hit.setAttribute("aria-valuenow", i+1);
    hit.setAttribute("aria-valuetext", `${stamp}, ${count}, variation ${change} unités, cumul ${signed(p.value)} unités`);
  }
  function hide() {
    tooltip.hidden = true;
    wrap.classList.remove("is-hovered");
  }
  function pointer(event) {
    const bounds = svg.getBoundingClientRect();
    const px = (event.clientX-bounds.left)*width/bounds.width;
    show(points.reduce((best,p,i) => Math.abs(p.x-px) < Math.abs(points[best].x-px) ? i : best, 0));
  }
  hit.addEventListener("pointermove", pointer);
  hit.addEventListener("pointerdown", pointer);
  hit.addEventListener("pointerleave", event => { if (event.pointerType !== "touch") hide(); });
  hit.addEventListener("pointercancel", hide);
  hit.addEventListener("focus", () => show(index));
  hit.addEventListener("blur", hide);
  hit.addEventListener("keydown", event => {
    const positions = {Home:0, End:points.length-1, ArrowLeft:index-1, ArrowRight:index+1, ArrowDown:index-1, ArrowUp:index+1};
    if (event.key === "Escape") { hide(); return; }
    if (!(event.key in positions)) return;
    event.preventDefault();
    show(Math.max(0, Math.min(points.length-1,positions[event.key])));
  });
}


function aggregatePeriods(rows) {
  if (!Array.isArray(rows)) return [];
  const periods = new Map();
  rows.forEach((row) => {
    if (!/^\d{4}-\d{2}$/.test(row?.month || "")) return;
    const [year, month] = row.month.split("-").map(Number);
    const profit = numberOrNull(row.profit);
    const bets = numberOrNull(row.bets);
    if (!Number.isInteger(year) || !Number.isInteger(month) || profit === null || bets === null) return;
    const start = month >= 8 ? year : year - 1;
    const current = periods.get(start) || { start, profit: 0, bets: 0 };
    current.profit += profit;
    current.bets += bets;
    periods.set(start, current);
  });
  return [...periods.values()].sort((a, b) => a.start - b.start).map((period) => ({
    ...period,
    label: `${period.start}/${String(period.start + 1).slice(-2)}`,
  }));
}

function renderPeriods(periods) {
  const holder = $("#period-chart");
  if (!holder) return;
  if (!periods.length) {
    holder.innerHTML = '<p class="empty-results">Résultats par période indisponibles.</p>';
    setText("#negative-periods", "—");
    return;
  }
  const maxAbsolute = Math.max(...periods.map((period) => Math.abs(period.profit)), 1);
  holder.innerHTML = periods.map((period) => {
    const negative = period.profit < 0;
    const width = Math.max(1, (Math.abs(period.profit) / maxAbsolute) * 48);
    return `
      <div class="period-row">
        <span class="period-label">${escapeHtml(period.label)}</span>
        <div class="period-bar" title="${integer.format(period.bets)} choix">
          <i class="${negative ? "negative" : "positive"}" style="width:${width}%"></i>
        </div>
        <strong class="period-value ${negative ? "negative" : "positive"}">${escapeHtml(signed(period.profit))}</strong>
      </div>`;
  }).join("");
  const negatives = periods.filter((period) => period.profit < 0).length;
  setText("#negative-periods", `${negatives} sur ${periods.length}`);
}

function renderPlausibleRange(metrics) {
  const low = numberOrNull(metrics.roiCiLow);
  const high = numberOrNull(metrics.roiCiHigh);
  const observed = numberOrNull(metrics["roi"]);
  if (low === null || high === null || observed === null) {
    setText("#range-copy", "La fourchette n’est pas disponible pour cette période.");
    return;
  }
  const low100 = low * 100;
  const high100 = high * 100;
  const observed100 = observed * 100;
  const rawMin = Math.min(low100, observed100, 0);
  const rawMax = Math.max(high100, observed100, 0);
  const padding = Math.max(3, (rawMax - rawMin) * .12);
  const domainMin = rawMin - padding;
  const domainMax = rawMax + padding;
  const position = (value) => scaleLinear(value, domainMin, domainMax, 0, 100);
  const bandLeft = position(Math.min(low100, high100));
  const bandRight = position(Math.max(low100, high100));
  $("#range-band").style.left = `${bandLeft}%`;
  $("#range-band").style.width = `${bandRight - bandLeft}%`;
  $("#range-zero").style.left = `${position(0)}%`;
  $("#range-observed").style.left = `${position(observed100)}%`;
  setText("#range-low", `${signed(low100, decimalOne)} mises`);
  setText("#range-high", `${signed(high100, decimalOne)} mises`);
  setText("#range-center", "Point d’équilibre");
  const crossesZero = low100 <= 0 && high100 >= 0;
  setText(
    "#range-copy",
    `Pour 100 mises identiques, la fourchette va de ${signed(low100, decimalOne)} à ${signed(high100, decimalOne)} mises. Le résultat observé est ${signed(observed100, decimalOne)}. ${crossesZero ? "Comme la fourchette traverse le point d’équilibre, un résultat positif n’est pas assuré." : "La fourchette reste du même côté du point d’équilibre."}`,
  );
  $("#range-visual")?.setAttribute("aria-label", `Fourchette de ${signed(low100, decimalOne)} à ${signed(high100, decimalOne)}, résultat observé ${signed(observed100, decimalOne)}`);
}

function renderStrategies(rows) {
  const holder = $("#strategy-list");
  if (!holder) return;
  const strategies = Array.isArray(rows) ? rows : [];
  if (!strategies.length) {
    holder.innerHTML = '<p class="empty-results">Résultats par stratégie indisponibles.</p>';
    return;
  }
  const maxAbsolute = Math.max(...strategies.map(row => Math.abs(row.profit ?? 0)), .01);
  holder.innerHTML = strategies.map(row => {
    const profit = numberOrNull(row.profit);
    const roi = numberOrNull(row.roi);
    const negative = profit !== null && profit < 0;
    const width = profit === null ? 0 : Math.abs(profit) / maxAbsolute * 50;
    return `
      <div class="strategy-row">
        <strong>${escapeHtml(row.label)}</strong>
        <b class="strategy-gain ${profit === null || profit === 0 ? "" : negative ? "negative" : "positive"}">${profit === null ? "—" : escapeHtml(signed(profit)) + " u"}</b>
        <span class="strategy-stats">${integer.format(row.bets)} pari${row.bets === 1 ? "" : "s"} terminé${row.bets === 1 ? "" : "s"} · Rendement : ${roi === null ? "—" : escapeHtml(signed(roi * 100, decimalOne)) + " %"}</span>
        <div class="strategy-meter" aria-hidden="true"><i class="${negative ? "negative" : "positive"}" style="width:${width}%"></i></div>
      </div>`;
  }).join("");
}

// Public results are calculated only from the current season's published ledger.
// Never substitute a training benchmark when live results are missing.
function currentSeasonData(data, now = Date.now()) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone:MATCH_TIMEZONE,year:'numeric',month:'2-digit'}).formatToParts(new Date(now));
  const year = Number(parts.find(p => p.type === 'year').value);
  const month = Number(parts.find(p => p.type === 'month').value);
  const season = month >= 7 ? year : year - 1;
  const seasonOf = date => {
    const d = new Date(date);
    if (!Number.isFinite(d.getTime())) return null;
    const p = new Intl.DateTimeFormat('en-CA',{timeZone:MATCH_TIMEZONE,year:'numeric',month:'2-digit'}).formatToParts(d);
    const y = Number(p.find(v => v.type === 'year').value);
    return Number(p.find(v => v.type === 'month').value) >= 7 ? y : y - 1;
  };
  const unique = new Map();
  for (const row of Array.isArray(data.activity) ? data.activity : []) {
    if (row.recommended !== true || row.historicalOnly === true || seasonOf(row.date) !== season) continue;
    const key = [row.league,row.homeTeam,row.awayTeam, new Intl.DateTimeFormat('en-CA',{timeZone:MATCH_TIMEZONE}).format(new Date(row.date)),row.outcomeLabel].join('|');
    if (!unique.has(key) || terminalResult(row)) unique.set(key,row);
  }
  const activity = [...unique.values()].sort((a,b) => new Date(a.date)-new Date(b.date));
  const settled = activity.filter(r => ['won','lost'].includes(r.status) && new Date(r.date).getTime() <= now);
  const publicStrategies = data.meta?.publicStrategies || [
    {league:'Bundesliga',outcome:'draw',label:'Bundesliga · match nul'},
    {id:'epl_away_logit_strict_2026_10_18',league:'EPL',outcome:'away_win',label:'Premier League · victoire extérieure'},
  ];
  const strategies = publicStrategies.map(strategy => {
    const rows = settled.filter(row => row.league === strategy.league
      && (row.outcome || ({'Match nul':'draw','Victoire extérieure':'away_win','Victoire à domicile':'home_win','Victoire domicile':'home_win'})[row.outcomeLabel]) === strategy.outcome
      && (!strategy.id || row.strategy === strategy.id)
      && !(strategy.excludeStrategyIds || []).includes(row.strategy));
    const known = rows.every(row => numberOrNull(row.profitUnits) !== null);
    const gain = known ? rows.reduce((sum,row) => sum + Number(row.profitUnits),0) : null;
    return {label:strategy.label,bets:rows.length,profit:gain,roi:known && rows.length ? gain / rows.length : null};
  });
  const complete = settled.every(r => numberOrNull(r.profitUnits) !== null);
  const won = settled.filter(r => r.status === 'won').length;
  let profit = 0, peak = 0, maxDrawdown = 0;
  const monthly = new Map(), leagues = new Map(), curve = [];
  for (const row of complete ? settled : []) {
    profit += Number(row.profitUnits);
    peak = Math.max(peak,profit);
    maxDrawdown = Math.min(maxDrawdown,profit-peak);
    curve.push({date:row.date,value:profit,drawdown:profit-peak});
    const m = new Intl.DateTimeFormat('en-CA',{timeZone:MATCH_TIMEZONE,year:'numeric',month:'2-digit'}).format(new Date(row.date));
    for (const [map,key] of [[monthly,m],[leagues,row.leagueLabel || row.league]]) {
      const group = map.get(key) || {label:key,leagueLabel:key,bets:0,profit:0};
      group.bets++; group.profit += Number(row.profitUnits); group.roi=group.profit/group.bets;
      map.set(key,group);
    }
  }
  const roi = complete && settled.length ? profit/settled.length : null;
  const metrics = {betCount:settled.length,profit:complete && settled.length ? profit:null,roi,hitRate:settled.length ? won/settled.length:null,maxDrawdown:settled.length && complete ? maxDrawdown:null,roiCiLow:null,roiCiHigh:null};
  return {...data, meta:{...data.meta,currentSeason:season},activity,
    predictions:(data.predictions || []).filter(r => seasonOf(r.date) === season),
    tracking:{...data.tracking,verified:settled.length,won,lost:settled.length-won},
    performance:{metrics,curve,strategies,monthly:[...monthly.values()],leagues:[...leagues.values()],live:{settledBets:settled.length,roi,profitUnits:metrics.profit}},
    summary:{...data.summary,liveReturn:roi,liveProfitUnits:metrics.profit}};
}

function renderPerformance(data) {
  try {
    const performance = data.performance || {};
    const metrics = performance.metrics || {};
    const summary = data.summary || {};
    const betCount = numberOrNull(metrics.betCount);
    const profit = numberOrNull(metrics.profit);
    const historicalReturn = numberOrNull(metrics["roi"]);
    const hitRate = numberOrNull(metrics.hitRate);
    const averageOdds = numberOrNull(metrics.averageOdds);
    const maxDrawdown = numberOrNull(metrics.maxDrawdown);
    setText("#test-selections", betCount === null ? "—" : integer.format(betCount));
    setText("#test-profit", profit === null ? "—" : `${signed(profit)} mises`);
    setText("#test-return", historicalReturn === null ? "—" : `${signed(historicalReturn * 100, decimalOne)} %`);
    setText("#test-hit-rate", hitRate === null ? "—" : percent.format(hitRate));
    setText("#test-average-odds", averageOdds === null ? "—" : decimal.format(averageOdds));
    setText("#test-range", profit === null ? "—" : `${signed(profit)} mises`);
    setText("#test-max-drawdown", maxDrawdown === null ? "—" : `${decimal.format(Math.abs(maxDrawdown))} mises`);
    setText("#cumulative-foot-value", profit === null ? "—" : `${signed(profit)} mises`);

    const scope = performance.scope || {};
    setText(
      "#performance-date-range",
      scope.startDate && scope.endDate
        ? `${formatFullDate(scope.startDate)} — ${formatFullDate(scope.endDate)} · résultat après chaque choix`
        : "Résultat après chaque choix historique.",
    );

    const periods = performance.monthly || [];
    displayedChartRows = performance.curve || [];
    renderCumulativeChart(displayedChartRows);
    renderPeriods(periods);
    renderPlausibleRange(metrics);
    renderStrategies(performance.strategies || []);

    setText("#range-low", metrics.roiCiLow === null ? "—" : `${signed(metrics.roiCiLow * 100, decimalOne)} %`);
    setText("#range-high", metrics.roiCiHigh === null ? "—" : `${signed(metrics.roiCiHigh * 100, decimalOne)} %`);
  } catch (e) {
    console.error("renderPerformance error:", e);
  }
}

function renderDashboard(data) {
  try {
    const serviceNotice = document.getElementById('service-notice');
    if (serviceNotice) {
      const message = data.meta.serviceNotice || '';
      const redundant = message.startsWith('Sélections exceptionnelles : xG Sportmonks ;')
        || message.startsWith('Understat indisponible : nouveaux paris limités à Angleterre domicile.');
      serviceNotice.textContent = redundant ? '' : message;
      serviceNotice.hidden = !serviceNotice.textContent;
    }
    data = currentSeasonData(data);
    const seasonLabel = `${data.meta.currentSeason}/${String(data.meta.currentSeason+1).slice(-2)}`;
    setText('#season-scope', `Saison ${seasonLabel} · 1 unité par pari`);
    const ready = data.meta.status === "ready";
    const fresh = publicationIsFresh(data.meta.generatedAt);
    const futurePredictions = matchCards(ready ? data : {...data, predictions:[], activity:[]});
    const visibleData = { ...data, predictions: futurePredictions };

    if (ready && fresh) {
      renderPredictions(visibleData);
      $("#load-error").hidden = true;
    } else if (futurePredictions.length > 0) {
      renderPredictions(visibleData);
      $("#load-error").textContent = "La mise à jour est en retard. Les choix publiés restent visibles, sans supposer de nouveau résultat.";
      $("#load-error").hidden = false;
    } else {
      const withoutCurrentDecision = {
        ...data,
        summary: { ...data.summary, upcomingBets: 0, currentRecommendations: 0 },
        predictions: [],
      };
      renderPredictions(withoutCurrentDecision);
      setText(".no-pick-kicker", ready ? "Publication à actualiser" : "Préparation en cours");
      setText(".no-pick-label", ready ? "Aucun pari à venir" : "Aucun pari disponible");
      setText(".no-pick-copy", "Le tableau de bord réessaie automatiquement et affichera la prochaine décision confirmée");
      $("#load-error").textContent = ready
        ? "La dernière publication a plus de 24 heures et ne contient plus de match à venir."
        : "Les données du jour sont encore en préparation. Aucun choix n'est présenté avant leur validation.";
      $("#load-error").hidden = false;
    }
    renderTracking(data);
    renderPerformance(data);
  } catch (e) {
    console.error("renderDashboard error:", e);
  }
}

function renderLoadError() {
  try {
    $("#load-error").hidden = false;
    $("#pick-list").hidden = true;
    $("#no-pick").hidden = false;
    $("#no-pick")?.classList.add("error-state");
    setText("#pick-count", "Données indisponibles");
    setText(".no-pick-kicker", "Données non confirmées");
    setText(".no-pick-label", "Les choix publiés sont indisponibles");
    setText(".no-pick-copy", "Aucun ancien choix n'est présenté comme actuel et une nouvelle tentative aura lieu automatiquement");
  } catch (e) {
    console.error("renderLoadError error:", e);
  }
}

let latestDashboard = null;
// A missing or failed asset must never hide the match or show a broken image.
document.addEventListener("error", event => {
  if (event.target.matches(".team-crest, .club-crest")) event.target.hidden = true;
}, true);
async function loadDashboard() {
  try {
    const data = await fetchDashboard();
    renderDashboard(data);
    latestDashboard = data;
  } catch (error) {
    latestDashboard = null;
    console.error(error);
    renderLoadError();
  }
}

const menuButton = $("#menu-button");
const mobileNav = $("#mobile-nav");
const menuBackground = [$("#main"), $(".site-footer"), $(".site-header .brand"), $(".header-status")].filter(Boolean);
let returnFocus = null;

function setBackgroundInert(value) {
  menuBackground.forEach((element) => { element.inert = value; });
}

function closeMenu({ restoreFocus = true } = {}) {
  if (!menuButton || !mobileNav) return;
  const wasOpen = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Ouvrir le menu");
  mobileNav.setAttribute("aria-hidden", "true");
  mobileNav.classList.remove("open");
  mobileNav.inert = true;
  document.body.classList.remove("menu-open");
  setBackgroundInert(false);
  if (wasOpen && restoreFocus && returnFocus?.focus) returnFocus.focus();
}

function openMenu() {
  if (!menuButton || !mobileNav) return;
  returnFocus = document.activeElement;
  menuButton.setAttribute("aria-expanded", "true");
  menuButton.setAttribute("aria-label", "Fermer le menu");
  mobileNav.setAttribute("aria-hidden", "false");
  mobileNav.classList.add("open");
  mobileNav.inert = false;
  document.body.classList.add("menu-open");
  setBackgroundInert(true);
  setTimeout(() => $("a", mobileNav)?.focus({ preventScroll: true }), 80);
}

if (menuButton && mobileNav) {
  mobileNav.inert = true;
  menuButton.addEventListener("click", () => {
    if (menuButton.getAttribute("aria-expanded") === "true") closeMenu();
    else openMenu();
  });
  $$("a", mobileNav).forEach((link) => link.addEventListener("click", () => closeMenu({ restoreFocus: false })));

  document.addEventListener("keydown", (event) => {
    if (menuButton.getAttribute("aria-expanded") !== "true") return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [menuButton, ...$$("a", mobileNav)];
    if (event.shiftKey && document.activeElement === focusable[0]) {
      event.preventDefault();
      focusable.at(-1).focus();
    } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
      event.preventDefault();
      focusable[0].focus();
    }
  });

  window.matchMedia("(min-width: 1121px)").addEventListener("change", (event) => {
    if (event.matches) closeMenu({ restoreFocus: false });
  });
}

if ("IntersectionObserver" in window) {
  const revealObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("visible");
      observer.unobserve(entry.target);
    });
  }, { threshold: .1, rootMargin: "0px 0px -4%" });
  $$("[data-reveal]").forEach((element) => revealObserver.observe(element));
} else {
  $$("[data-reveal]").forEach((element) => element.classList.add("visible"));
}

const film = $("#match-film");
const videoToggle = $("#video-toggle");
let userPausedFilm = true;

function syncVideoControl() {
  if (!film || !videoToggle) return;
  const playing = !film.paused;
  videoToggle.classList.toggle("playing", playing);
  videoToggle.setAttribute("aria-label", playing ? "Mettre la vidéo en pause" : "Lire la vidéo");
  setText("#video-label", playing ? "Pause" : "Lire");
}

if (film && videoToggle) {
  videoToggle.addEventListener("click", async () => {
    if (film.paused) {
      userPausedFilm = false;
      await film.play().catch(() => {});
    } else {
      userPausedFilm = true;
      film.pause();
    }
    syncVideoControl();
  });
  film.addEventListener("play", syncVideoControl);
  film.addEventListener("pause", syncVideoControl);
  film.addEventListener("ended", () => { userPausedFilm = true; syncVideoControl(); });

  if ("IntersectionObserver" in window) {
    const filmObserver = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) film.pause();
      else if (!userPausedFilm && !reducedMotion.matches) film.play().catch(() => {});
    }, { threshold: .2 });
    filmObserver.observe(film);
  }
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) {
      userPausedFilm = true;
      film.pause();
    }
  });
}

setText("#current-year", String(new Date().getFullYear()));
syncVideoControl();
loadDashboard();
if ("ResizeObserver" in window) {
  const chartWidths = new WeakMap();
  const chartObserver = new ResizeObserver((entries) => {
    const changed = entries.map(({ target, contentRect }) => {
      const width = Math.round(contentRect.width);
      if (chartWidths.get(target) === width) return false;
      chartWidths.set(target, width);
      return true;
    }).some(Boolean);
    if (changed) {
      renderCumulativeChart(displayedChartRows);
    }
  });
  $$("#cumulative-chart").forEach(svg => chartObserver.observe(svg.parentElement));
}
setInterval(loadDashboard, 5 * 60 * 1000);
// Update the kickoff state locally without an extra network poll or invented live score.
setInterval(() => { if (latestDashboard) renderDashboard(latestDashboard); }, 30 * 1000);
