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
  return data.predictions.filter((prediction) => {
    const kickoff = new Date(prediction.date).getTime();
    return Number.isFinite(kickoff) && kickoff > now && inPublicWindow(prediction.date, now);
  });
}

function parisDay(value) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: MATCH_TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function matchCards(data, now = Date.now()) {
  const key = row => [row.league, row.homeTeam, row.awayTeam, parisDay(row.date)].join('|');
  const cards = new Map(futurePublishedPredictions(data, now).map(row => [key(row), row]));
  // The ledger takes over after kickoff, even when the daily export no longer has the prediction.
  for (const row of [...data.predictions, ...(data.activity || [])]) {
    const kickoff = new Date(row.date).getTime();
    if (row.recommended !== true || !Number.isFinite(kickoff) || kickoff > now) continue;
    const previous = cards.get(key(row));
    if (previous && terminalResult(previous) && !terminalResult(row)) continue;
    cards.set(key(row), {...previous, ...row, started: true});
  }
  return [...cards.values()].filter(row => !terminalResult(row) || parisDay(row.date) === parisDay(now))
    .sort((a,b) => new Date(a.date)-new Date(b.date));
}

function inPublicWindow(value, now = Date.now()) {
  if (!Number.isFinite(new Date(value).getTime())) return false;
  const today = Date.parse(`${parisDay(now)}T00:00:00Z`);
  const day = Date.parse(`${parisDay(value)}T00:00:00Z`);
  return day >= today && day < today + 3 * 86400000;
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
    && Number.isInteger(examined) && examined >= upcoming
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

const LEAGUE_COUNTRIES = Object.freeze({
  EPL: "Angleterre",
  Bundesliga: "Allemagne",
  Serie_A: "Italie",
  Ligue_1: "France",
  La_liga: "Espagne",
});

function predictionMarkup(prediction) {
  if (prediction.started) return followedMatchMarkup(prediction);
  const league = prediction.leagueLabel || prediction.league || "Championnat";
  const country = LEAGUE_COUNTRIES[prediction.league] || league;
  const modelIndex = numberOrNull(prediction.modelProbability) ?? 0;
  const modelIndexWidth = Math.max(0, Math.min(100, modelIndex * 100));
  return `
    <article class="prediction" aria-label="${escapeHtml(`${prediction.homeTeam} contre ${prediction.awayTeam}, ${prediction.outcomeLabel}`)}">
      <div class="prediction-head">
        <span class="prediction-league"><i aria-hidden="true"></i>${escapeHtml(league)}</span>
        <time datetime="${escapeHtml(prediction.date)}">${escapeHtml(formatDate(prediction.date, true))}</time>
      </div>
      <div class="prediction-pitch" aria-hidden="true"><i></i></div>
      <div class="teams">
        <p>${escapeHtml(country)}</p>
        <h2>${escapeHtml(prediction.homeTeam)}</h2>
        <span>contre</span>
        <h2>${escapeHtml(prediction.awayTeam)}</h2>
        <div class="prediction-choice">
          <strong>${escapeHtml(prediction.outcomeLabel)}</strong>
        </div>
      </div>
      <div class="prediction-confidence" aria-label="Indice du modèle pour ${escapeHtml(prediction.outcomeLabel.toLowerCase())} : ${escapeHtml(percent.format(modelIndex))}">
        <div><span>Indice du modèle</span><b>${escapeHtml(percent.format(modelIndex))}</b></div>
        <i aria-hidden="true"><span style="width: ${modelIndexWidth.toFixed(1)}%"></span></i>
      </div>
      <div class="prediction-footer">
        <div><span>Cote</span><b>${decimal.format(prediction.odds)}</b></div>
        <div><span>Mise indicative</span><b>${decimal.format(prediction.stakeEur)} €</b></div>
      </div>
    </article>`;
}

function followedMatchMarkup(match) {
  const confirmed = terminalResult(match);
  const score = confirmed && match.status !== 'void' && match.actualScore ? match.actualScore : '—';
  const label = resultLabel(match.status, match.date);
  const odds = numberOrNull(match.odds);
  return `<article class="prediction prediction-followed" aria-label="${escapeHtml(`${match.homeTeam} contre ${match.awayTeam}, ${label}`)}">
    <div class="prediction-head"><span>${escapeHtml(match.leagueLabel || match.league)}</span><time datetime="${escapeHtml(match.date)}">${escapeHtml(formatDate(match.date,true))}</time></div>
    <div class="prediction-pitch" aria-hidden="true"><i></i></div>
    <div class="teams"><p>Football</p><h2>${escapeHtml(match.homeTeam)}</h2><span>contre</span><h2>${escapeHtml(match.awayTeam)}</h2></div>
    ${confirmed ? `<div class="match-verdict" role="status"><strong>${escapeHtml(score)}</strong><span>${escapeHtml(label)}</span></div>` : ''}
    <div class="prediction-footer"><div><b>${escapeHtml(match.outcomeLabel)}</b></div><div><span>Cote publiée</span><b>${odds === null ? '—' : decimal.format(odds)}</b></div></div>
  </article>`;
}

function resetNoPickCopy() {
  setText(".no-pick .section-label", "Décision enregistrée");
  setText(".no-pick strong", "Aucun match retenu pour le moment");
  setText(".no-pick > p:last-child", "Les prochains choix apparaîtront ici");
  $("#no-pick")?.classList.remove("error-state");
}

function renderPredictions(data) {
  try {
    const predictions = data.predictions;
    const holder = $("#pick-list");
    const hasPredictions = predictions.length > 0;
    holder.hidden = !hasPredictions;
    $("#no-pick").hidden = hasPredictions;
    resetNoPickCopy();
    const awaitingResult = (data.activity || []).some(row => row.recommended === true && !terminalResult(row) && new Date(row.date).getTime() <= Date.now());
    if (!hasPredictions && awaitingResult) {
      setText(".no-pick .section-label", "Le suivi continue");
      setText(".no-pick strong", "Aucun autre match à venir");
      setText(".no-pick > p:last-child", "Les rencontres déjà commencées restent dans les résultats ci-dessous");
    }
    const markup = predictions.map((prediction) => predictionMarkup(prediction)).join("");
    if (holder.dataset.markup !== markup) {
      holder.innerHTML = markup;
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

function resultMarkup(row) {
  return `<div class="result-row">
    <time datetime="${escapeHtml(row.date || "")}">${escapeHtml(formatDate(row.date, true))}</time>
    <strong>${escapeHtml(row.homeTeam)} <span class="result-versus">—</span> ${escapeHtml(row.awayTeam)}</strong>
    <span>${escapeHtml(row.outcomeLabel || "Choix publié")}</span>
    <div class="result-verdict">${row.actualScore ? `<strong class="final-score">${escapeHtml(row.actualScore)}</strong>` : ""}<b class="${row.status === "won" ? "won" : row.status === "lost" ? "lost" : ""}">${resultLabel(row.status, row.date)}</b></div>
  </div>`;
}

function renderHistory() {
  const visible = historyRows.filter(row => historyFilter === "all" || (historyFilter === "settled" ? terminalResult(row) : !terminalResult(row) && new Date(row.date).getTime() > Date.now()));
  let month = '';
  const markup = visible.slice(0, historyLimit).map(row => {
    const date = new Date(row.date);
    const label = Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('fr-FR', {month:'long',year:'numeric',timeZone:MATCH_TIMEZONE}).format(date) : 'Date à confirmer';
    const heading = label !== month ? `<h3 class="history-month">${escapeHtml(label)}</h3>` : '';
    month = label;
    return heading + resultMarkup(row);
  }).join('');
  $("#result-list").innerHTML = markup || '<p class="empty-results">Aucune décision dans cette catégorie pour le moment</p>';
  $("#history-more").hidden = visible.length <= historyLimit;
}

$("#history-more")?.addEventListener('click', () => { historyLimit += 8; renderHistory(); });

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

let roiPoints = [];
let roiSignature = '';
function selectRoiPoint(index) {
  const point = roiPoints[index];
  if (!point) return;
  setText('#roi-caption', `${formatDate(point.date)} · ${point.homeTeam} — ${point.awayTeam} · ${signed(point.roi,decimalOne)} %`);
  $('#roi-cursor')?.setAttribute('cx', point.x);
  $('#roi-cursor')?.setAttribute('cy', point.y);
  $('#roi-position')?.setAttribute('aria-valuetext', `${point.homeTeam} contre ${point.awayTeam}, rendement observé ${signed(point.roi,decimalOne)} pour cent`);
}

$('#roi-position')?.addEventListener('input', event => selectRoiPoint(Number(event.target.value)));

function renderLiveCurve(rows, verified, expectedRoi) {
  const nextPoints = liveRoiPoints(rows, verified, expectedRoi);
  const signature = JSON.stringify(nextPoints);
  if (signature === roiSignature) return;
  roiSignature = signature;
  roiPoints = nextPoints;
  $('#live-curve').hidden = roiPoints.length === 0;
  if (!roiPoints.length) return;
  const low = Math.min(0,...roiPoints.map(p=>p.roi));
  const high = Math.max(0,...roiPoints.map(p=>p.roi));
  const y = value => 104-(value-low)/(high-low || 1)*88;
  roiPoints = roiPoints.map((point,i) => ({...point,x:12+i/(roiPoints.length-1)*576,y:y(point.roi)}));
  $('#roi-line').setAttribute('d', roiPoints.map((p,i)=>`${i?'L':'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' '));
  $('#roi-zero').setAttribute('y1',y(0));
  $('#roi-zero').setAttribute('y2',y(0));
  const slider = $('#roi-position');
  slider.max = roiPoints.length-1;
  slider.value = slider.max;
  selectRoiPoint(roiPoints.length-1);
}

function renderTracking(data) {
  try {
    const tracking = data.tracking || {};
    const performanceLive = data.performance?.live || {};
    const allRows = (Array.isArray(data.activity) ? data.activity : []).filter(row => row?.recommended === true);
    const pending = allRows.filter(row => !terminalResult(row) && inPublicWindow(row.date)).length;
    const verified = numberOrNull(tracking.verified) ?? numberOrNull(performanceLive.settledBets) ?? 0;
    const won = numberOrNull(tracking.won) ?? 0;
    const lost = numberOrNull(tracking.lost) ?? 0;
    renderLiveCurve(allRows, verified, performanceLive.roi ?? data.summary.liveReturn);
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
    historyRows = allRows.filter(row => new Date(row.date).getTime() <= Date.now() || inPublicWindow(row.date))
      .sort((a, b) => new Date(b.date) - new Date(a.date));
    renderHistory();
  } catch (e) {
    console.error("renderTracking error:", e);
  }
}

function usableCurve(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.map((row) => ({
    date: row?.date,
    timestamp: new Date(row?.date).getTime(),
    value: numberOrNull(row?.value),
    drawdown: numberOrNull(row?.drawdown),
  })).filter((row) => Number.isFinite(row.timestamp) && row.value !== null);
}

function scaleLinear(value, domainMin, domainMax, rangeMin, rangeMax) {
  if (domainMax === domainMin) return (rangeMin + rangeMax) / 2;
  return rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
}

function pathFromPoints(points) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
}

function renderCumulativeChart(rows) {
  const svg = $("#cumulative-chart");
  const tooltip = $("#cumulative-tooltip");
  if (!svg) return;
  const curve = usableCurve(rows);
  if (curve.length < 2) {
    svg.innerHTML = '<text x="480" y="180" text-anchor="middle" class="chart-axis">La courbe apparaîtra après deux paris terminés cette saison</text>';
    return;
  }

  const width = 960;
  const height = 360;
  const margin = { top: 18, right: 22, bottom: 42, left: 62 };
  const timestamps = curve.map((row) => row.timestamp);
  const values = curve.map((row) => row.value);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  const padding = Math.max(4, (rawMax - rawMin) * .1);
  const min = rawMin - padding;
  const max = rawMax + padding;
  const x = (value) => scaleLinear(value, timestamps[0], timestamps.at(-1), margin.left, width - margin.right);
  const y = (value) => scaleLinear(value, min, max, height - margin.bottom, margin.top);
  const points = curve.map((row) => ({ ...row, x: x(row.timestamp), y: y(row.value) }));
  const line = pathFromPoints(points);
  const baseline = y(0);
  const area = `${line} L${points.at(-1).x.toFixed(2)},${baseline.toFixed(2)} L${points[0].x.toFixed(2)},${baseline.toFixed(2)} Z`;

  const yTicks = Array.from({ length: 5 }, (_, index) => max - ((max - min) * index) / 4);
  const grid = yTicks.map((tick) => {
    const yValue = y(tick);
    return `<line class="chart-grid" x1="${margin.left}" x2="${width - margin.right}" y1="${yValue}" y2="${yValue}"></line><text class="chart-axis" x="${margin.left - 12}" y="${yValue + 4}" text-anchor="end">${escapeHtml(signed(tick, decimalOne))}</text>`;
  }).join("");
  const xTickIndexes = [0, .25, .5, .75, 1].map((ratio) => Math.round((curve.length - 1) * ratio));
  const xTicks = [...new Set(xTickIndexes)].map((index) => {
    const point = points[index];
    const label = new Intl.DateTimeFormat("fr-FR", { month: "short", year: "2-digit" }).format(new Date(point.timestamp));
    return `<text class="chart-axis" x="${point.x}" y="${height - 10}" text-anchor="middle">${escapeHtml(label)}</text>`;
  }).join("");

  svg.innerHTML = `
    <title id="cumulative-chart-title">Évolution cumulée des résultats passés</title>
    <desc id="cumulative-chart-desc">La courbe part de ${escapeHtml(signed(curve[0].value))} mise et termine à ${escapeHtml(signed(curve.at(-1).value))} mises</desc>
    <defs>
      <linearGradient id="history-area" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#1f8f5b" stop-opacity=".24"></stop>
        <stop offset="100%" stop-color="#1f8f5b" stop-opacity=".02"></stop>
      </linearGradient>
    </defs>
    ${grid}
    <line class="chart-zero" x1="${margin.left}" x2="${width - margin.right}" y1="${baseline}" y2="${baseline}"></line>
    ${xTicks}
    <path class="chart-area" d="${area}"></path>
    <path class="chart-line" d="${line}"></path>
    <line class="chart-focus-line" x1="0" x2="0" y1="${margin.top}" y2="${height - margin.bottom}"></line>
    <circle class="chart-focus-dot" cx="0" cy="0" r="5"></circle>
    <circle class="chart-end" cx="${points.at(-1).x}" cy="${points.at(-1).y}" r="5"></circle>
    <rect class="chart-hit" x="${margin.left}" y="${margin.top}" width="${width - margin.left - margin.right}" height="${height - margin.top - margin.bottom}" tabindex="0" role="group" aria-label="Explorer les résultats passés avec les flèches gauche et droite"></rect>
  `;

  const hitArea = $(".chart-hit", svg);
  const focusLine = $(".chart-focus-line", svg);
  const focusDot = $(".chart-focus-dot", svg);
  const wrap = svg.parentElement;
  let keyboardIndex = points.length - 1;
  const showPoint = (nearest) => {
    focusLine.setAttribute("x1", nearest.x);
    focusLine.setAttribute("x2", nearest.x);
    focusDot.setAttribute("cx", nearest.x);
    focusDot.setAttribute("cy", nearest.y);
    tooltip.innerHTML = `${escapeHtml(formatChartDate(nearest.date))}<strong>${escapeHtml(signed(nearest.value))} mises</strong>`;
    tooltip.style.left = `${(nearest.x / width) * 100}%`;
    tooltip.style.top = `${(nearest.y / height) * 100}%`;
    tooltip.hidden = false;
    wrap.classList.add("is-hovered");
    hitArea.setAttribute("aria-label", `${formatChartDate(nearest.date)}, ${signed(nearest.value)} mises. Flèches gauche et droite pour parcourir`);
  };
  const hidePoint = () => {
    tooltip.hidden = true;
    wrap.classList.remove("is-hovered");
  };
  const handlePointer = (event) => {
    const bounds = hitArea.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const targetX = margin.left + ratio * (width - margin.left - margin.right);
    let nearest = points[0];
    for (const point of points) {
      if (Math.abs(point.x - targetX) < Math.abs(nearest.x - targetX)) nearest = point;
    }
    showPoint(nearest);
  };
  hitArea.addEventListener("pointermove", handlePointer);
  hitArea.addEventListener("pointerleave", hidePoint);
  hitArea.addEventListener("focus", () => showPoint(points[keyboardIndex]));
  hitArea.addEventListener("blur", hidePoint);
  hitArea.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") keyboardIndex = 0;
    else if (event.key === "End") keyboardIndex = points.length - 1;
    else if (event.key === "ArrowLeft") keyboardIndex = Math.max(0, keyboardIndex - 1);
    else keyboardIndex = Math.min(points.length - 1, keyboardIndex + 1);
    showPoint(points[keyboardIndex]);
  });
}

function renderDrawdownChart(rows) {
  const svg = $("#drawdown-chart");
  if (!svg) return;
  const curve = usableCurve(rows).filter((row) => row.drawdown !== null);
  if (curve.length < 2) {
    svg.innerHTML = '<text x="480" y="130" text-anchor="middle" class="chart-axis">Données de baisse indisponibles</text>';
    return;
  }

  const width = 960;
  const height = 260;
  const margin = { top: 18, right: 22, bottom: 35, left: 62 };
  const min = Math.min(...curve.map((row) => row.drawdown), -1) * 1.08;
  const max = 0;
  const x = (value) => scaleLinear(value, curve[0].timestamp, curve.at(-1).timestamp, margin.left, width - margin.right);
  const y = (value) => scaleLinear(value, min, max, height - margin.bottom, margin.top);
  const points = curve.map((row) => ({ ...row, x: x(row.timestamp), y: y(row.drawdown) }));
  const line = pathFromPoints(points);
  const baseline = y(0);
  const area = `M${points[0].x},${baseline} ${line.slice(1)} L${points.at(-1).x},${baseline} Z`;
  const ticks = [0, .33, .66, 1].map((ratio) => min * ratio);
  const grid = ticks.map((tick) => {
    const yValue = y(tick);
    return `<line class="chart-grid" x1="${margin.left}" x2="${width - margin.right}" y1="${yValue}" y2="${yValue}"></line><text class="chart-axis" x="${margin.left - 12}" y="${yValue + 4}" text-anchor="end">${escapeHtml(signed(tick, decimalOne))}</text>`;
  }).join("");
  const xTickIndexes = [0, .33, .66, 1].map((ratio) => Math.round((curve.length - 1) * ratio));
  const xTicks = [...new Set(xTickIndexes)].map((index) => {
    const point = points[index];
    return `<text class="chart-axis" x="${point.x}" y="${height - 8}" text-anchor="middle">${new Date(point.timestamp).getFullYear()}</text>`;
  }).join("");

  svg.innerHTML = `
    <title id="drawdown-chart-title">Baisses historiques depuis le meilleur niveau atteint</title>
    <desc id="drawdown-chart-desc">La baisse la plus importante observée est de ${escapeHtml(signed(Math.min(...curve.map((row) => row.drawdown))))} mises</desc>
    <defs>
      <linearGradient id="drawdown-area" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#e87c6f" stop-opacity=".05"></stop>
        <stop offset="100%" stop-color="#e87c6f" stop-opacity=".4"></stop>
      </linearGradient>
    </defs>
    ${grid}${xTicks}
    <path class="drawdown-area" d="${area}"></path>
    <path class="drawdown-line" d="${line}"></path>
  `;
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
    holder.innerHTML = '<p class="empty-results">Résultats par période indisponibles</p>';
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
    setText("#range-copy", "La fourchette n’est pas disponible pour cette période");
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
    `Pour 100 mises identiques, la fourchette va de ${signed(low100, decimalOne)} à ${signed(high100, decimalOne)} mises. Le résultat observé est ${signed(observed100, decimalOne)}. ${crossesZero ? "Comme la fourchette traverse le point d’équilibre, un résultat positif n’est pas assuré" : "La fourchette reste du même côté du point d’équilibre"}`,
  );
  $("#range-visual")?.setAttribute("aria-label", `Fourchette de ${signed(low100, decimalOne)} à ${signed(high100, decimalOne)}, résultat observé ${signed(observed100, decimalOne)}`);
}

function renderLeagues(rows) {
  const holder = $("#league-list");
  if (!holder) return;
  const leagues = (Array.isArray(rows) ? rows : []).map((row) => ({
    label: row?.leagueLabel || row?.league,
    bets: numberOrNull(row?.bets),
    result: numberOrNull(row?.["roi"]),
  })).filter((row) => validText(row.label) && row.bets !== null && row.result !== null);
  if (!leagues.length) {
    holder.innerHTML = '<p class="empty-results">Résultats par championnat indisponibles</p>';
    return;
  }
  const maxAbsolute = Math.max(...leagues.map((row) => Math.abs(row.result)), .01);
  holder.innerHTML = leagues.map((row) => {
    const result100 = row.result * 100;
    const negative = result100 < 0;
    const width = Math.max(2, Math.min(100, (Math.abs(row.result) / maxAbsolute) * 100));
    return `
      <div class="league-row">
        <strong>${escapeHtml(row.label)}</strong>
        <span>${integer.format(row.bets)} choix</span>
        <div class="league-meter" aria-hidden="true"><i class="${negative ? "negative" : ""}" style="width:${width}%"></i></div>
        <b class="league-result ${negative ? "negative" : "positive"}">${escapeHtml(signed(result100, decimalOne))} / 100</b>
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
    if (row.recommended !== true || seasonOf(row.date) !== season) continue;
    const key = [row.league,row.homeTeam,row.awayTeam, new Intl.DateTimeFormat('en-CA',{timeZone:MATCH_TIMEZONE}).format(new Date(row.date)),row.outcomeLabel].join('|');
    if (!unique.has(key) || terminalResult(row)) unique.set(key,row);
  }
  const activity = [...unique.values()].sort((a,b) => new Date(a.date)-new Date(b.date));
  const settled = activity.filter(r => ['won','lost'].includes(r.status) && new Date(r.date).getTime() <= now);
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
    performance:{metrics,curve,monthly:[...monthly.values()],leagues:[...leagues.values()],live:{settledBets:settled.length,roi,profitUnits:metrics.profit}},
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
        : "Résultat après chaque choix historique",
    );

    const periods = performance.monthly || [];
    renderCumulativeChart(performance.curve || []);
    renderDrawdownChart(performance.curve || []);
    renderPeriods(periods);
    renderPlausibleRange(metrics);
    renderLeagues(performance.leagues || []);

    setText("#max-drawdown", maxDrawdown === null ? "—" : `${decimal.format(Math.abs(maxDrawdown))} mises`);
    setText("#positive-periods", periods.length ? `${periods.filter(p => p.profit > 0).length} sur ${periods.length}` : "—");
    setText("#range-low", metrics.roiCiLow === null ? "—" : `${signed(metrics.roiCiLow * 100, decimalOne)} %`);
    setText("#range-high", metrics.roiCiHigh === null ? "—" : `${signed(metrics.roiCiHigh * 100, decimalOne)} %`);
  } catch (e) {
    console.error("renderPerformance error:", e);
  }
}

function renderDashboard(data) {
  try {
    data = currentSeasonData(data);
    const seasonLabel = `${data.meta.currentSeason}/${String(data.meta.currentSeason+1).slice(-2)}`;
    setText('#season-scope', `Saison ${seasonLabel}. Uniquement les paris réellement publiés et leurs résultats confirmés`);
    setText('#tracking-scope', `Saison ${seasonLabel} · stratégie actuellement publiée`);
    const ready = data.meta.status === "ready";
    const fresh = publicationIsFresh(data.meta.generatedAt);
    const futurePredictions = matchCards(data);
    const visibleData = { ...data, predictions: futurePredictions };

    if (ready && fresh) {
      renderPredictions(visibleData);
      $("#load-error").hidden = true;
    } else if (ready && futurePredictions.length > 0) {
      renderPredictions(visibleData);
      $("#load-error").textContent = "La mise à jour est en retard. Les choix publiés restent visibles, sans supposer de nouveau résultat";
      $("#load-error").hidden = false;
    } else {
      const withoutCurrentDecision = {
        ...data,
        summary: { ...data.summary, upcomingBets: 0, currentRecommendations: 0 },
        predictions: [],
      };
      renderPredictions(withoutCurrentDecision);
      setText(".no-pick .section-label", ready ? "Publication à actualiser" : "Préparation en cours");
      setText(".no-pick strong", ready ? "Aucun choix à venir dans la dernière publication" : "Aucun choix n'est encore disponible");
      setText(".no-pick > p:last-child", "Le tableau de bord réessaie automatiquement et affichera la prochaine décision confirmée");
      $("#load-error").textContent = ready
        ? "La dernière publication a plus de 24 heures et ne contient plus de match à venir"
        : "Les données du jour sont encore en préparation. Aucun choix n'est présenté avant leur validation";
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
    setText(".no-pick .section-label", "Données non confirmées");
    setText(".no-pick strong", "La décision du jour est indisponible");
    setText(".no-pick > p:last-child", "Aucun ancien choix n'est présenté comme actuel. Une nouvelle tentative aura lieu automatiquement");
  } catch (e) {
    console.error("renderLoadError error:", e);
  }
}

let latestDashboard = null;
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
setInterval(loadDashboard, 5 * 60 * 1000);
// Update the kickoff state locally without an extra network poll or invented live score.
setInterval(() => { if (latestDashboard) renderDashboard(latestDashboard); }, 30 * 1000);
