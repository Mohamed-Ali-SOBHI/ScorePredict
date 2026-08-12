document.documentElement.classList.add("js");

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const integer = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
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
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
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

function isValidPrediction(prediction) {
  if (!prediction || prediction.recommended !== true) return false;
  const odds = numberOrNull(prediction.odds);
  const probability = numberOrNull(prediction.modelProbability);
  const stake = numberOrNull(prediction.stakeEur);
  const date = new Date(prediction.date);

  return validText(prediction.homeTeam)
    && validText(prediction.awayTeam)
    && validText(prediction.outcomeLabel)
    && validText(prediction.riskLabel)
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

function predictionMarkup(prediction, index, total) {
  const league = prediction.leagueLabel || prediction.league || "Championnat";
  const heading = total > 1 ? `Pronostic ${index + 1} · ${league}` : league;
  return `
    <article class="prediction">
      <div class="prediction-head">
        <span>${escapeHtml(heading)}</span>
        <time datetime="${escapeHtml(prediction.date)}">${escapeHtml(formatDate(prediction.date, true))}</time>
      </div>
      <div class="teams">
        <h2>${escapeHtml(prediction.homeTeam)}</h2>
        <span>—</span>
        <h2>${escapeHtml(prediction.awayTeam)}</h2>
      </div>
      <div class="recommendation">
        <span>Pari recommandé</span>
        <strong>${escapeHtml(prediction.outcomeLabel)}</strong>
      </div>
      <div class="prediction-data">
        <div><span>Cote</span><b>${decimal.format(prediction.odds)}</b></div>
        <div><span>Chance estimée</span><b>${percent.format(prediction.modelProbability)}</b></div>
        <div><span>Mise indicative</span><b>${decimal.format(prediction.stakeEur)} €</b></div>
        <div><span>Prudence</span><b>${escapeHtml(prediction.riskLabel)}</b></div>
      </div>
      <p class="prediction-note">Estimation publiée avant le match. Aucun résultat n’est garanti.</p>
    </article>`;
}

function renderMeta(data) {
  const season = `${data.meta.currentSeason}/${String(data.meta.currentSeason + 1).slice(-2)}`;
  const ready = data.meta.status === "ready";
  setText("#current-season", season);
  setText("#header-state", ready ? "Données du jour prêtes" : "Préparation en cours");
  setText("#published-time", `Mis à jour le ${formatDate(data.meta.generatedAt, true)}`);
  $(".status-dot")?.classList.toggle("ready", ready);
}

function renderPredictions(data) {
  const predictions = data.predictions;
  const holder = $("#pick-list");
  const hasPredictions = predictions.length > 0;
  holder.hidden = !hasPredictions;
  $("#no-pick").hidden = hasPredictions;
  setText(
    "#hero-title",
    !hasPredictions ? "Aucun pari forcé aujourd’hui." : predictions.length > 1 ? "Les choix retenus, sans détour." : "Le choix retenu, sans détour.",
  );

  setText(
    "#analysis-summary",
    hasPredictions
      ? `${integer.format(data.summary.scoredFixtures)} matchs ont été examinés. ${predictions.length > 1 ? `${integer.format(predictions.length)} ont été retenus` : "Un seul a été retenu"}.`
      : `${integer.format(data.summary.scoredFixtures)} matchs ont été examinés. Aucun pari n’est recommandé aujourd’hui.`,
  );
  holder.innerHTML = predictions.map((prediction, index) => predictionMarkup(prediction, index, predictions.length)).join("");
}

function renderExplanation(data) {
  const prediction = data.predictions[0];
  const retained = data.predictions.length;
  setText("#analysis-total", integer.format(data.summary.scoredFixtures));
  setText("#analysis-retained", integer.format(retained));
  setText("#retained-label", retained > 1 ? "paris retenus" : "pari retenu");
  $("#why-panel").classList.toggle("without-pick", !prediction);

  if (!prediction) {
    setText("#why-title", "Aucune différence suffisante aujourd’hui.");
    setText("#why-copy", "Les estimations disponibles ne justifient pas la publication d’un pari.");
    return;
  }

  const rawMarketProbability = numberOrNull(prediction.marketProbability);
  const marketProbability = rawMarketProbability !== null && rawMarketProbability >= 0 && rawMarketProbability <= 1 ? rawMarketProbability : null;
  const gap = marketProbability === null ? null : prediction.modelProbability - marketProbability;
  setText("#why-title", `Pourquoi ${prediction.outcomeLabel.toLowerCase()} ?`);
  setText(
    "#why-copy",
    gap === null
      ? "Notre estimation franchit les seuils nécessaires pour publier ce pari."
      : `Notre estimation dépasse de ${Math.round(gap * 100)} points ce que la cote laisse entendre. C’est l’écart qui a permis à ce match de franchir les contrôles.`,
  );
  setText("#model-chance", percent.format(prediction.modelProbability));
  setText("#market-chance", marketProbability === null ? "—" : percent.format(marketProbability));
  setText("#odds-value", decimal.format(prediction.odds));
  setText("#stake-value", `${decimal.format(prediction.stakeEur)} €`);
  setText("#risk-value", prediction.riskLabel);
  $("#model-bar").style.width = `${Math.min(100, prediction.modelProbability * 100)}%`;
  $("#market-bar").style.width = marketProbability === null ? "0%" : `${Math.min(100, marketProbability * 100)}%`;
}

function resultLabel(status) {
  if (status === "won") return "Gagné";
  if (status === "lost") return "Perdu";
  if (status === "void") return "Annulé";
  return "En attente";
}

function renderTracking(data) {
  const tracking = data.tracking || {};
  setText("#tracking-pending", integer.format(numberOrNull(tracking.pending) ?? 0));
  setText("#tracking-won", integer.format(numberOrNull(tracking.won) ?? 0));
  setText("#tracking-lost", integer.format(numberOrNull(tracking.lost) ?? 0));
  setText("#memory-title", tracking.storageReady ? "Historique permanent actif" : "Historique enregistré localement");
  setText(
    "#memory-copy",
    tracking.storageReady
      ? "Les paris et leurs résultats sont conservés entre chaque mise à jour."
      : "Les résultats restent disponibles sur cette installation.",
  );
  $("#memory-dot")?.classList.toggle("ready", Boolean(tracking.storageReady));

  const verified = (data.activity || []).filter((row) => ["won", "lost", "void"].includes(row.status));
  const holder = $("#result-list");
  if (!verified.length) {
    holder.innerHTML = '<p class="empty-results">Les premiers résultats apparaîtront ici après les matchs recommandés.</p>';
    return;
  }

  holder.innerHTML = verified.slice(0, 8).map((row) => `
    <div class="result-row">
      <time>${escapeHtml(formatDate(row.date))}</time>
      <strong>${escapeHtml(row.homeTeam)} — ${escapeHtml(row.awayTeam)}</strong>
      <span>${escapeHtml(row.outcomeLabel || "Pronostic")}${row.actualScore ? ` · ${escapeHtml(row.actualScore)}` : ""}</span>
      <b class="${row.status === "won" ? "won" : ""}">${resultLabel(row.status)}</b>
    </div>
  `).join("");
}

function renderDashboard(data) {
  renderMeta(data);
  renderPredictions(data);
  renderExplanation(data);
  renderTracking(data);
  $("#load-error").hidden = true;
}

async function loadDashboard() {
  try {
    renderDashboard(await fetchDashboard());
  } catch (error) {
    console.error(error);
    $("#load-error").hidden = false;
    setText("#header-state", "Données indisponibles");
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

mobileNav.inert = true;
menuButton.addEventListener("click", () => {
  if (menuButton.getAttribute("aria-expanded") === "true") closeMenu();
  else openMenu();
});
$$('a', mobileNav).forEach((link) => link.addEventListener("click", () => closeMenu({ restoreFocus: false })));

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

window.matchMedia("(min-width: 1051px)").addEventListener("change", (event) => {
  if (event.matches) closeMenu({ restoreFocus: false });
});

const revealObserver = new IntersectionObserver((entries, observer) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add("visible");
    observer.unobserve(entry.target);
  });
}, { threshold: .12, rootMargin: "0px 0px -5%" });
$$('[data-reveal]').forEach((element) => revealObserver.observe(element));

const film = $("#match-film");
const videoToggle = $("#video-toggle");
let userPausedFilm = true;

function syncVideoControl() {
  const playing = !film.paused;
  videoToggle.classList.toggle("playing", playing);
  videoToggle.setAttribute("aria-label", playing ? "Mettre la vidéo en pause" : "Lire la vidéo");
  setText("#video-label", playing ? "Pause" : "Lire");
}

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

const filmObserver = new IntersectionObserver(([entry]) => {
  if (!entry?.isIntersecting) film.pause();
  else if (!userPausedFilm && !reducedMotion.matches) film.play().catch(() => {});
}, { threshold: .2 });
filmObserver.observe(film);
reducedMotion.addEventListener("change", () => {
  if (reducedMotion.matches) {
    userPausedFilm = true;
    film.pause();
  }
});

setText("#current-year", String(new Date().getFullYear()));
syncVideoControl();
loadDashboard();
setInterval(loadDashboard, 5 * 60 * 1000);
