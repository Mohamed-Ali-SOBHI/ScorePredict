const state = { data: null, league: "all", search: "" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const number = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const percent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" });
const plainPercent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 1 });
const currency = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function isRecommendedOnlyPayload(data) {
  const predictions = data?.predictions;
  return Array.isArray(predictions)
    && predictions.every((prediction) => prediction.recommended === true)
    && Number(data?.summary?.upcomingBets) === predictions.length;
}

async function fetchDashboard(force = false) {
  const apiUrl = `/api/v1/dashboard${force ? "?refresh=1" : ""}`;
  const githubPages = window.location.hostname.endsWith(".github.io");
  if (!githubPages) {
    try {
      const response = await fetch(apiUrl, { headers: { Accept: "application/json" }, cache: "no-store" });
      if (!response.ok || !(response.headers.get("content-type") || "").includes("application/json")) throw new Error("API unavailable");
      const data = await response.json();
      if (!isRecommendedOnlyPayload(data)) throw new Error("Stale publication contract");
      return data;
    } catch {
      // Un hébergement statique lit directement le dernier export validé.
    }
  }
  const snapshotUrl = `./data/dashboard.json?v=${Date.now()}`;
  const response = await fetch(snapshotUrl, { cache: "no-store" });
  if (!response.ok) throw new Error("Dashboard snapshot unavailable");
  const data = await response.json();
  if (!isRecommendedOnlyPayload(data)) throw new Error("Invalid dashboard snapshot");
  return data;
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function formatDate(value, options = {}) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", ...options }).format(date);
}

function formatSync(value) {
  if (!value) return "Dernière synchronisation —";
  const date = new Date(value);
  return `Calculé le ${new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date)}`;
}

function riskClass(label) {
  if (label === "Élevé") return "high";
  if (label === "Faible") return "low";
  return "medium";
}

function renderMeta(data) {
  const { meta, quality } = data;
  setText("#season-label", `Saison ${meta.currentSeason}/${String(meta.currentSeason + 1).slice(-2)}`);
  setText("#last-sync", formatSync(meta.generatedAt));
  setText("#sidebar-status", meta.statusLabel);
  const dot = $("#sidebar-status-dot");
  dot.className = `status-dot ${meta.status}`;

  const banner = $("#system-banner");
  banner.className = `system-banner reveal ${meta.status}`;
  if (meta.status === "ready") {
    setText("#banner-title", "Les prévisions sont prêtes");
    setText("#banner-copy", "Les données sont à jour et les prochains choix peuvent être affichés.");
  } else if (meta.status === "blocked") {
    setText("#banner-title", "Les prévisions sont temporairement bloquées");
    setText("#banner-copy", `${quality.criticalFailures} vérification(s) importante(s) doivent être corrigées avant publication.`);
  } else {
    setText("#banner-title", "Nouvelle saison à mettre à jour");
    setText("#banner-copy", "Les données récentes doivent être mises à jour. Aucune ancienne prévision ne sera réutilisée.");
  }
}

function renderSummary(data) {
  const { summary, risk, tracking } = data;
  setText("#metric-upcoming", integer.format(data.predictions.length));
  setText("#metric-fixtures", `${integer.format(summary.scoredFixtures)} match${summary.scoredFixtures > 1 ? "s" : ""} analysé${summary.scoredFixtures > 1 ? "s" : ""}`);
  setText("#metric-pending", integer.format(tracking.pending));
  setText("#metric-verified", integer.format(tracking.verified));
  setText("#metric-verified-detail", `${integer.format(tracking.won)} gagnée${tracking.won > 1 ? "s" : ""} · ${integer.format(tracking.lost)} perdue${tracking.lost > 1 ? "s" : ""}`);
  setText("#metric-risk", `${risk.score}/100`);
  setText("#metric-risk-label", `niveau ${risk.label.toLowerCase()}`);
}

function renderLeagueFilters(predictions) {
  const leagues = [...new Map(predictions.map((prediction) => [prediction.league, prediction.leagueLabel])).entries()];
  const holder = $("#league-filters");
  holder.innerHTML = `<button class="active" type="button" data-league="all">Tous</button>${leagues.map(([code, label]) => `<button type="button" data-league="${escapeHtml(code)}">${escapeHtml(label)}</button>`).join("")}`;
  holder.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-league]");
    if (!button) return;
    state.league = button.dataset.league;
    $$("button", holder).forEach((item) => item.classList.toggle("active", item === button));
    renderPredictions();
  });
}

function predictionRow(prediction) {
  const date = new Date(prediction.date);
  const time = Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(date);
  return `<tr data-prediction-id="${escapeHtml(prediction.id)}" tabindex="0">
    <td class="date-cell"><strong>${escapeHtml(formatDate(prediction.date))}</strong><small>${escapeHtml(time)} · ${escapeHtml(prediction.leagueLabel)}</small></td>
    <td class="match-cell"><strong>${escapeHtml(prediction.homeTeam)}</strong><small>vs ${escapeHtml(prediction.awayTeam)}</small></td>
    <td><span class="selection">${escapeHtml(prediction.outcomeLabel)}</span><small class="selection-note">Pari recommandé</small></td>
    <td class="number">${number.format(prediction.odds)}</td>
    <td><span class="risk-pill ${riskClass(prediction.riskLabel)}">${escapeHtml(prediction.riskLabel)}</span></td>
    <td class="row-arrow">›</td>
  </tr>`;
}

function renderPredictions() {
  const source = state.data?.predictions || [];
  const query = state.search.trim().toLocaleLowerCase("fr");
  const filtered = source.filter((prediction) => {
    const leagueMatch = state.league === "all" || prediction.league === state.league;
    const text = `${prediction.homeTeam} ${prediction.awayTeam} ${prediction.leagueLabel}`.toLocaleLowerCase("fr");
    return leagueMatch && (!query || text.includes(query));
  });
  $("#prediction-body").innerHTML = filtered.map(predictionRow).join("");
  $("#prediction-empty").hidden = filtered.length > 0;
  $$('[data-prediction-id]').forEach((row) => {
    const open = () => openDrawer(source.find((item) => item.id === row.dataset.predictionId));
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") open(); });
  });
}

function pointsFor(values, width, height, pad) {
  const min = Math.min(0, ...values);
  const max = Math.max(1, ...values);
  const range = max - min || 1;
  return values.map((value, index) => ({
    x: pad + (index / Math.max(1, values.length - 1)) * (width - pad * 2),
    y: pad + ((max - value) / range) * (height - pad * 2),
    value,
  }));
}

function renderProfitChart(curve) {
  const holder = $("#profit-chart");
  if (!curve.length) { holder.innerHTML = '<div class="empty-state"><strong>Courbe indisponible</strong></div>'; return; }
  const width = 800, height = 280, pad = 30;
  const values = curve.map((row) => Number(row.value));
  const points = pointsFor(values, width, height, pad);
  const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${line} L${points.at(-1).x},${height - pad} L${points[0].x},${height - pad} Z`;
  const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
  const zeroY = pad + ((max - 0) / range) * (height - pad * 2);
  const grid = [0, .25, .5, .75, 1].map((ratio) => {
    const y = pad + ratio * (height - pad * 2);
    const label = max - ratio * range;
    return `<line class="chart-grid" x1="${pad}" y1="${y}" x2="${width - pad}" y2="${y}"/><text class="chart-axis-label" x="0" y="${y + 3}">${number.format(label)}</text>`;
  }).join("");
  holder.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}<line class="zero-line" x1="${pad}" y1="${zeroY}" x2="${width - pad}" y2="${zeroY}"/><path class="profit-area" d="${area}"/><path class="profit-line" d="${line}"/><circle class="profit-dot" cx="${points.at(-1).x}" cy="${points.at(-1).y}" r="4"/></svg>`;
}

function renderMonthlyChart(rows) {
  const holder = $("#monthly-chart");
  if (!rows.length) { holder.textContent = "Données indisponibles"; return; }
  const width = 400, height = 280, pad = 28;
  const values = rows.map((row) => Number(row.profit));
  const maxAbs = Math.max(.01, ...values.map(Math.abs));
  const zero = height / 2;
  const slot = (width - pad * 2) / rows.length;
  const bars = rows.map((row, index) => {
    const value = Number(row.profit);
    const barHeight = Math.max(2, Math.abs(value) / maxAbs * (height / 2 - pad - 10));
    const x = pad + index * slot + slot * .2;
    const y = value >= 0 ? zero - barHeight : zero;
    const label = String(row.month).slice(5);
    return `<rect class="${value >= 0 ? "bar-positive" : "bar-negative"}" x="${x}" y="${y}" width="${slot * .6}" height="${barHeight}" rx="1"><title>${escapeHtml(row.month)} : ${value >= 0 ? "+" : ""}${number.format(value)}</title></rect><text class="chart-axis-label" x="${x + slot * .3}" y="${height - 5}" text-anchor="middle">${escapeHtml(label)}</text>`;
  }).join("");
  holder.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><line class="zero-line" x1="${pad}" y1="${zero}" x2="${width - pad}" y2="${zero}"/>${bars}</svg>`;
}

function renderPerformance(performance) {
  const metrics = performance.metrics;
  setText("#performance-scope", performance.scope.label);
  setText("#chart-profit", `${metrics.profit >= 0 ? "+" : ""}${number.format(metrics.profit)}`);
  setText("#chart-period", `${formatDate(performance.scope.startDate, { year: "numeric" })} — ${formatDate(performance.scope.endDate, { year: "numeric" })}`);
  const bestMonth = [...performance.monthly].sort((a, b) => b.profit - a.profit)[0];
  setText("#month-highlight", bestMonth ? `${bestMonth.profit >= 0 ? "+" : ""}${number.format(bestMonth.profit)}` : "—");
  setText("#evidence-level", performance.evidence.level);
  setText("#evidence-copy", "Les résultats passés sont positifs, mais ils ne garantissent pas les prochains matchs.");
  setText("#tracked-bets", integer.format(metrics.betCount));
  setText("#winning-bets", `${integer.format(Math.round(metrics.hitRate * metrics.betCount))} / ${integer.format(metrics.betCount)}`);
  setText("#largest-drop", `${metrics.maxDrawdown >= 0 ? "" : ""}${number.format(metrics.maxDrawdown)}`);
  renderProfitChart(performance.curve);
  renderMonthlyChart(performance.monthly);
  const maxLeagueProfit = Math.max(1, ...performance.leagues.map((row) => Math.abs(Number(row.profit))));
  $("#league-breakdown").innerHTML = performance.leagues.map((row) => { const profit = Number(row.profit); return `<div class="league-row"><strong>${escapeHtml(row.leagueLabel)}</strong><div class="league-track"><i class="${profit < 0 ? "negative" : ""}" style="width:${clamp(Math.abs(profit) / maxLeagueProfit * 100, 0, 100)}%"></i></div><b class="${profit < 0 ? "negative" : ""}">${profit >= 0 ? "+" : ""}${number.format(profit)}</b><span class="league-profit">${integer.format(Number(row.bets))} suivis</span><span class="league-volume">${plainPercent.format(Number(row.hit_rate))} gagnants</span></div>`; }).join("");
}

function renderTracking(tracking) {
  setText("#memory-scope", tracking.storageLabel);
  setText("#tracking-rate", tracking.hitRate == null ? "—" : plainPercent.format(tracking.hitRate));
  setText(
    "#tracking-copy",
    tracking.verified
      ? `${integer.format(tracking.verified)} prévision${tracking.verified > 1 ? "s" : ""} contrôlée${tracking.verified > 1 ? "s" : ""} avec un score final.`
      : "Le calcul commencera dès que des prévisions publiées auront un résultat final.",
  );
  setText("#tracking-pending", integer.format(tracking.pending));
  setText("#tracking-won", integer.format(tracking.won));
  setText("#tracking-lost", integer.format(tracking.lost));
  setText("#tracking-void", integer.format(tracking.void));
  setText("#memory-title", tracking.storageReady ? "Historique permanent" : "Historique local");
  setText("#memory-copy", tracking.storageCopy);
  $("#memory-status").classList.toggle("ready", tracking.storageReady);
}

function renderRisk(risk) {
  setText("#risk-score", risk.score);
  setText("#risk-level", risk.label);
  setText("#risk-recommendation", risk.recommendation);
  setText("#risk-method", "Plus le niveau est élevé, plus il vaut mieux attendre avant de suivre un nouveau choix.");
  const circumference = 2 * Math.PI * 66;
  const ring = $("#ring-value");
  ring.style.strokeDasharray = String(circumference);
  ring.style.strokeDashoffset = String(circumference * (1 - risk.score / 100));
  ring.style.stroke = risk.score >= 70 ? "var(--danger)" : risk.score < 40 ? "var(--success)" : "var(--warning)";
  $("#risk-components").innerHTML = risk.components.map((component) => { const ratio = component.score / component.max; const level = ratio >= .67 ? "Important" : ratio >= .34 ? "À surveiller" : "Faible"; return `<article class="risk-component"><header><span>${escapeHtml(component.label)}</span><strong>${level}</strong></header><div class="risk-bar"><i style="width:${clamp(ratio * 100, 0, 100)}%"></i></div><p>${escapeHtml(component.detail)}</p></article>`; }).join("");
}

function renderQuality(quality) {
  setText("#quality-matches", integer.format(quality.rawMatches));
  const from = quality.dateRange.from ? formatDate(quality.dateRange.from, { year: "numeric" }) : "—";
  const to = quality.dateRange.to ? formatDate(quality.dateRange.to, { year: "numeric" }) : "—";
  setText("#quality-rows", from !== "—" && to !== "—" ? `${from} — ${to}` : "—");
  setText("#quality-features", quality.expectedSeasonTeams ? `${integer.format(quality.currentSeasonTeams)}/${integer.format(quality.expectedSeasonTeams)}` : "—");
  const currentSeasonCheck = quality.checks.find((check) => check.id === "season");
  const seasonReady = currentSeasonCheck?.status === "pass";
  setText("#quality-warnings", seasonReady ? "Prête" : "À faire");
  setText("#data-range", `Historique couvert ${from} — ${to}`);
  if (seasonReady && quality.overallStatus === "pass") {
    setText("#data-status-title", "Les données sont à jour.");
    setText("#data-status-copy", "Les prochaines prévisions peuvent être publiées avec la saison en cours.");
  } else if (!seasonReady) {
    setText("#data-status-title", "La nouvelle saison doit encore être préparée.");
    setText("#data-status-copy", "L’historique est conservé, mais aucune ancienne prévision ne sera réutilisée par erreur.");
  } else {
    setText("#data-status-title", "Une mise à jour est nécessaire avant de publier.");
    setText("#data-status-copy", "Les résultats historiques restent visibles pendant que les données récentes sont actualisées.");
  }
}

function renderActivity(activity) {
  $("#activity-body").innerHTML = activity.map((row) => {
    const won = row.status === "won";
    const voided = row.status === "void";
    const pending = !["won", "lost", "void"].includes(row.status);
    const label = pending ? "À vérifier" : voided ? "Annulée" : won ? "Gagnée" : "Perdue";
    const css = pending || voided ? "pending" : won ? "won" : "lost";
    return `<tr><td>${escapeHtml(formatDate(row.date, { year: "numeric" }))}</td><td class="match-cell"><strong>${escapeHtml(row.homeTeam)}</strong><small>vs ${escapeHtml(row.awayTeam)} · ${escapeHtml(row.leagueLabel)}</small></td><td class="match-cell"><strong>${escapeHtml(row.outcomeLabel)}</strong><small>Prévision publiée avant le match</small></td><td class="number">${escapeHtml(row.actualScore || "—")}</td><td><span class="result-pill ${css}">${label}</span></td></tr>`;
  }).join("");
  $("#tracking-empty").hidden = activity.length > 0;
}

function openDrawer(prediction) {
  if (!prediction) return;
  const advice = "Pari recommandé";
  const note = "Ce choix respecte tous les critères de la stratégie active pour ce championnat.";
  $("#drawer-content").innerHTML = `<p class="drawer-eyebrow">${escapeHtml(prediction.leagueLabel)} / PRÉVISION</p><h3 class="drawer-match">${escapeHtml(prediction.homeTeam)}<br>vs ${escapeHtml(prediction.awayTeam)}</h3><p class="drawer-date">${escapeHtml(formatDate(prediction.date, { year: "numeric", hour: "2-digit", minute: "2-digit" }))}</p><div class="drawer-decision"><div><span>${advice}</span><strong>${escapeHtml(prediction.outcomeLabel)}</strong></div><b>${number.format(prediction.odds)}</b></div><div class="drawer-facts"><div><span>Championnat</span><strong>${escapeHtml(prediction.leagueLabel)}</strong></div><div><span>Prudence</span><strong>${escapeHtml(prediction.riskLabel)}</strong></div><div><span>Avis</span><strong>${advice}</strong></div><div><span>Moment</span><strong>Avant le match</strong></div></div><p class="drawer-note">${note} Aucun résultat n’est garanti.</p>`;
  const drawer = $("#detail-drawer"), backdrop = $("#drawer-backdrop");
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
  backdrop.hidden = false; requestAnimationFrame(() => backdrop.classList.add("visible"));
  $("#drawer-close").focus();
}

function closeDrawer() {
  const drawer = $("#detail-drawer"), backdrop = $("#drawer-backdrop");
  drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.remove("visible"); setTimeout(() => { backdrop.hidden = true; }, 200);
}

function showToast(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2300);
}

function renderAll(data) {
  const recommendations = (data.predictions || []).filter((prediction) => prediction.recommended === true);
  state.data = { ...data, predictions: recommendations };
  $("#prediction-toolbar").hidden = recommendations.length <= 1;
  renderMeta(state.data); renderSummary(state.data); renderLeagueFilters(recommendations);
  renderPredictions(); renderTracking(state.data.tracking); renderRisk(state.data.risk);
  renderQuality(state.data.quality); renderActivity(state.data.activity);
}

async function load(force = false) {
  try {
    renderAll(await fetchDashboard(force));
    if (force) showToast("Données relues depuis les exports");
  } catch (error) {
    setText("#sidebar-status", "Indisponible");
    $("#sidebar-status-dot").className = "status-dot blocked";
    setText("#banner-title", "Le tableau de bord ne peut pas lire ses données");
    setText("#banner-copy", "Vérifiez la connexion puis réessayez.");
    console.error(error);
  } finally { /* La prochaine mise à jour est planifiée automatiquement. */ }
}

$("#prediction-search").addEventListener("input", (event) => { state.search = event.target.value; renderPredictions(); });
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
$("#mobile-menu").addEventListener("click", () => {
  const sidebar = $(".sidebar"); sidebar.classList.toggle("open");
  $("#mobile-menu").setAttribute("aria-expanded", String(sidebar.classList.contains("open")));
});
$$('.nav-item').forEach((link) => link.addEventListener("click", () => $(".sidebar").classList.remove("open")));

const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
  if (!entry.isIntersecting) return;
  $$('.nav-item').forEach((link) => link.classList.toggle("active", link.dataset.section === entry.target.id));
}), { rootMargin: "-20% 0px -70% 0px" });
$$('main > section[id]').forEach((section) => observer.observe(section));

load();
setInterval(() => load(false), 5 * 60 * 1000);
