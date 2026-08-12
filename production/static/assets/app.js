document.documentElement.classList.add("motion-ready");

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

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function isFilledText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function isValidPrediction(prediction) {
  if (!prediction || prediction.recommended !== true) return false;
  const odds = finiteNumber(prediction.odds);
  const probability = finiteNumber(prediction.modelProbability);
  const stake = finiteNumber(prediction.stakeEur);
  const date = new Date(prediction.date);

  return isFilledText(prediction.homeTeam)
    && isFilledText(prediction.awayTeam)
    && isFilledText(prediction.outcomeLabel)
    && isFilledText(prediction.riskLabel)
    && !Number.isNaN(date.getTime())
    && odds !== null && odds > 1
    && probability !== null && probability > 0 && probability <= 1
    && stake !== null && stake > 0;
}

function formatDate(value, withTime = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function formatShortDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date);
}

function isRecommendedOnlyPayload(data) {
  if (!data || !data.meta || !data.summary || !Array.isArray(data.predictions)) return false;
  const upcomingBets = finiteNumber(data.summary.upcomingBets);
  const scoredFixtures = finiteNumber(data.summary.scoredFixtures);
  return Number.isInteger(upcomingBets) && upcomingBets >= 0
    && Number.isInteger(scoredFixtures) && scoredFixtures >= upcomingBets
    && data.predictions.length === upcomingBets
    && data.predictions.every(isValidPrediction);
}

async function fetchDashboard() {
  const githubPages = window.location.hostname.endsWith(".github.io");
  if (!githubPages) {
    try {
      const apiResponse = await fetch("/api/v1/dashboard", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (apiResponse.ok && (apiResponse.headers.get("content-type") || "").includes("application/json")) {
        const apiData = await apiResponse.json();
        if (isRecommendedOnlyPayload(apiData)) return apiData;
      }
    } catch {
      // Le site statique reste disponible quand l'API locale n'est pas lancée.
    }
  }

  const response = await fetch(`./data/dashboard.json?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Snapshot indisponible");
  const data = await response.json();
  if (!isRecommendedOnlyPayload(data)) throw new Error("Publication incomplète");
  return data;
}

function setCount(selector, value) {
  const element = $(selector);
  if (!element) return;
  element.dataset.count = String(Math.max(0, Math.round(safeNumber(value))));
  element.dataset.animated = "false";
  element.textContent = "0";
  countObserver.observe(element);
}

function renderMeta(data) {
  const { meta, summary } = data;
  const season = `${meta.currentSeason}/${String(meta.currentSeason + 1).slice(-2)}`;
  setText("#hero-season", season);
  setText("#header-state", meta.status === "ready" ? "Prêt" : "En préparation");
  setText(
    "#hero-proof",
    summary.upcomingBets
      ? `${integer.format(summary.scoredFixtures)} matchs étudiés · ${integer.format(summary.upcomingBets)} ${summary.upcomingBets > 1 ? "choix retenus" : "choix retenu"}`
      : `${integer.format(summary.scoredFixtures)} matchs étudiés · aucun choix aujourd’hui`,
  );
  setText("#pick-updated", `Analyse du ${formatShortDate(meta.generatedAt)}`);
  document.body.dataset.status = meta.status;
}

function renderPredictions(data) {
  const predictions = data.predictions;
  const hasPrediction = predictions.length > 0;
  const holder = $("#pick-list");
  holder.hidden = !hasPrediction;
  $("#no-pick").hidden = hasPrediction;
  setText("#pick-status", hasPrediction
    ? `${predictions.length} ${predictions.length > 1 ? "choix validés" : "choix validé"}`
    : "Aucun choix publié");
  setText("#pick-title-main", predictions.length > 1 ? `${predictions.length} choix retenus.` : hasPrediction ? "Un seul choix." : "Aucun choix forcé.");

  if (!hasPrediction) {
    holder.innerHTML = "";
    return;
  }

  holder.innerHTML = predictions.map((prediction, index) => {
    const league = prediction.leagueLabel || prediction.league || "Championnat";
    const listLabel = predictions.length > 1 ? `Choix ${String(index + 1).padStart(2, "0")} · ${league}` : league;
    return `
      <article class="pick-stage">
        <div class="pick-meta">
          <span>${escapeHtml(listLabel)}</span>
          <time datetime="${escapeHtml(prediction.date)}">${escapeHtml(formatDate(prediction.date, true))}</time>
        </div>
        <div class="matchup">
          <h3>${escapeHtml(prediction.homeTeam)}</h3>
          <span>contre</span>
          <h3>${escapeHtml(prediction.awayTeam)}</h3>
        </div>
        <div class="decision-line">
          <div><span>Notre choix</span><strong>${escapeHtml(prediction.outcomeLabel)}</strong></div>
          <dl>
            <div><dt>Cote proposée</dt><dd>${decimal.format(prediction.odds)}</dd></div>
            <div><dt>Chance estimée</dt><dd>${percent.format(prediction.modelProbability)}</dd></div>
            <div><dt>Mise indicative</dt><dd>${decimal.format(prediction.stakeEur)} €</dd></div>
            <div><dt>Prudence</dt><dd>${escapeHtml(prediction.riskLabel)}</dd></div>
          </dl>
        </div>
        <p class="pick-note">Une recommandation reste une estimation, jamais une promesse de résultat.</p>
      </article>`;
  }).join("");
}

function renderSelectivity(summary) {
  const fixtures = safeNumber(summary.scoredFixtures);
  const bets = safeNumber(summary.upcomingBets);
  setCount("#fixtures-count", fixtures);
  setCount("#bets-count", bets);
  setText("#bets-label", bets > 1 ? "retenus." : "retenu.");
  setText("#selection-ratio", `${String(bets).padStart(2, "0")} / ${String(fixtures).padStart(2, "0")}`);
}

function resultLabel(status) {
  if (status === "won") return "Gagné";
  if (status === "lost") return "Perdu";
  if (status === "void") return "Annulé";
  return "En attente";
}

function renderTracking(data) {
  const tracking = data.tracking || {};
  setCount("#tracking-pending", tracking.pending);
  setCount("#tracking-won", tracking.won);
  setCount("#tracking-lost", tracking.lost);
  setText("#memory-title", tracking.storageReady ? "Historique permanent activé" : "Historique local activé");
  setText(
    "#memory-copy",
    tracking.storageReady
      ? "Chaque choix et son résultat sont conservés entre les mises à jour."
      : "Le suivi est actif sur cette machine ; la synchronisation distante est indisponible.",
  );
  setText("#memory-sync", tracking.lastSyncAt ? `Mis à jour ${formatShortDate(tracking.lastSyncAt)}` : "—");
  $("#memory-dot").classList.toggle("ready", Boolean(tracking.storageReady));

  const verified = (data.activity || []).filter((row) => ["won", "lost", "void"].includes(row.status));
  const holder = $("#result-list");
  if (!verified.length) {
    holder.innerHTML = '<p class="empty-results">Les premiers résultats apparaîtront ici après les matchs recommandés.</p>';
    return;
  }

  holder.innerHTML = verified.slice(0, 5).map((row) => `
    <div class="result-row">
      <time>${formatDate(row.date)}</time>
      <strong>${escapeHtml(row.homeTeam)} — ${escapeHtml(row.awayTeam)}</strong>
      <span>${escapeHtml(row.outcomeLabel || "Prévision")}${row.actualScore ? ` · ${escapeHtml(row.actualScore)}` : ""}</span>
      <b class="${row.status === "won" ? "won" : ""}">${resultLabel(row.status)}</b>
    </div>
  `).join("");
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

function renderDashboard(data) {
  renderMeta(data);
  renderPredictions(data);
  renderSelectivity(data.summary);
  renderTracking(data);
  $("#load-error").hidden = true;
}

async function loadDashboard() {
  try {
    renderDashboard(await fetchDashboard());
  } catch (error) {
    console.error(error);
    $("#load-error").hidden = false;
    setText("#header-state", "Indisponible");
    setText("#pick-status", "Données momentanément indisponibles");
  }
}

const revealObserver = new IntersectionObserver((entries, observer) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add("is-visible");
    observer.unobserve(entry.target);
  });
}, { threshold: .12, rootMargin: "0px 0px -8%" });

$$('.reveal, .reveal-media').forEach((element) => revealObserver.observe(element));

const countObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting || entry.target.dataset.animated === "true") return;
    const element = entry.target;
    const target = safeNumber(element.dataset.count);
    element.dataset.animated = "true";

    if (reducedMotion.matches) {
      element.textContent = integer.format(target);
      return;
    }

    const start = performance.now();
    const duration = 850;
    const tick = (time) => {
      const progress = Math.min(1, (time - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = integer.format(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}, { threshold: .5 });

$$('[data-count]').forEach((element) => countObserver.observe(element));

const methodSteps = $$(".method-step");
const methodCounter = $("#method-counter");
const methodObserver = new IntersectionObserver((entries) => {
  const current = entries
    .filter((entry) => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!current) return;
  methodSteps.forEach((step) => step.classList.toggle("active", step === current.target));
  methodCounter.textContent = current.target.dataset.step;
}, { threshold: [.35, .6], rootMargin: "-25% 0px -35%" });
methodSteps.forEach((step) => methodObserver.observe(step));

const menuButton = $("#menu-button");
const mobileNav = $("#mobile-nav");
const menuBackground = [$("#main"), $(".site-footer"), $(".site-header .brand"), $(".desktop-nav"), $(".live-state"), $(".header-cta")].filter(Boolean);
let menuReturnFocus = null;

function setMenuBackgroundInert(inert) {
  menuBackground.forEach((element) => { element.inert = inert; });
}

function closeMenu({ restoreFocus = true } = {}) {
  const wasOpen = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Ouvrir le menu");
  mobileNav.classList.remove("open");
  mobileNav.setAttribute("aria-hidden", "true");
  mobileNav.inert = true;
  document.body.classList.remove("menu-open");
  setMenuBackgroundInert(false);
  if (wasOpen && restoreFocus && menuReturnFocus instanceof HTMLElement) menuReturnFocus.focus();
}

function openMenu() {
  menuReturnFocus = document.activeElement;
  menuButton.setAttribute("aria-expanded", "true");
  menuButton.setAttribute("aria-label", "Fermer le menu");
  mobileNav.classList.add("open");
  mobileNav.setAttribute("aria-hidden", "false");
  mobileNav.inert = false;
  document.body.classList.add("menu-open");
  setMenuBackgroundInert(true);
  setTimeout(() => $("a", mobileNav)?.focus({ preventScroll: true }), 80);
}

mobileNav.inert = true;
menuButton.addEventListener("click", () => {
  const open = menuButton.getAttribute("aria-expanded") !== "true";
  if (open) openMenu();
  else closeMenu();
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
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

window.matchMedia("(min-width: 1081px)").addEventListener("change", (event) => {
  if (event.matches) closeMenu({ restoreFocus: false });
});

const videoStates = new Map();

function updateVideoButton(state) {
  const paused = state.video.paused;
  state.button.classList.toggle("paused", paused);
  state.button.setAttribute("aria-label", paused ? "Lire la vidéo" : "Mettre la vidéo en pause");
  const label = $("[data-video-label]", state.button);
  if (label) label.textContent = paused ? "Lire le film" : "Pause film";
}

async function playVideo(state) {
  await state.video.play().catch(() => {});
  updateVideoButton(state);
}

$$('[data-video-target]').forEach((button) => {
  const video = $(`#${button.dataset.videoTarget}`);
  if (!video) return;
  const state = { video, button, visible: false, userPaused: reducedMotion.matches };
  videoStates.set(video, state);
  video.addEventListener("play", () => updateVideoButton(state));
  video.addEventListener("pause", () => updateVideoButton(state));
  button.addEventListener("click", async () => {
    if (video.paused) {
      state.userPaused = false;
      await playVideo(state);
    } else {
      state.userPaused = true;
      video.pause();
    }
  });
  updateVideoButton(state);
});

const videoObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    const state = videoStates.get(entry.target);
    if (!state) return;
    state.visible = entry.isIntersecting;
    if (state.visible && !state.userPaused && !reducedMotion.matches) playVideo(state);
    else state.video.pause();
  });
}, { threshold: .25 });
videoStates.forEach((state) => videoObserver.observe(state.video));

function syncMotionPreference() {
  videoStates.forEach((state) => {
    state.userPaused = reducedMotion.matches;
    if (reducedMotion.matches || !state.visible) state.video.pause();
    else playVideo(state);
    updateVideoButton(state);
  });
}
reducedMotion.addEventListener("change", syncMotionPreference);
syncMotionPreference();

let scrollFrame = 0;
function updateScrollEffects() {
  scrollFrame = 0;
  const scrollTop = window.scrollY;
  const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  $("#reading-progress").style.width = `${Math.min(100, scrollTop / maxScroll * 100)}%`;
  $("#site-header").classList.toggle("scrolled", scrollTop > 30);

  $$(".reveal-media:not(.is-visible)").forEach((media) => {
    const rect = media.getBoundingClientRect();
    if (rect.top < window.innerHeight * .94 && rect.bottom > 0) media.classList.add("is-visible");
  });

  const methodSection = $(".method-section");
  if (methodSection) {
    const sectionRect = methodSection.getBoundingClientRect();
    if (sectionRect.top < window.innerHeight && sectionRect.bottom > 0) {
      const focusLine = window.innerHeight * .56;
      const currentStep = methodSteps
        .filter((step) => {
          const rect = step.getBoundingClientRect();
          return rect.bottom > 0 && rect.top < window.innerHeight;
        })
        .sort((a, b) => Math.abs(a.getBoundingClientRect().top - focusLine) - Math.abs(b.getBoundingClientRect().top - focusLine))[0];
      if (currentStep) {
        methodSteps.forEach((step) => step.classList.toggle("active", step === currentStep));
        methodCounter.textContent = currentStep.dataset.step;
      }
    }
  }

  if (!reducedMotion.matches) {
    document.documentElement.style.setProperty("--hero-shift", `${Math.min(90, scrollTop * .14)}px`);
    const methodMedia = $(".method-media");
    if (methodMedia) {
      const rect = methodMedia.getBoundingClientRect();
      const progress = Math.max(0, Math.min(1, (window.innerHeight - rect.top) / (window.innerHeight + rect.height)));
      methodMedia.style.setProperty("--media-scale", String(1.065 - progress * .055));
    }
  }
}

window.addEventListener("scroll", () => {
  if (scrollFrame) return;
  scrollFrame = requestAnimationFrame(updateScrollEffects);
}, { passive: true });
window.addEventListener("resize", updateScrollEffects);
updateScrollEffects();

setText("#current-year", String(new Date().getFullYear()));
loadDashboard();
setInterval(loadDashboard, 5 * 60 * 1000);
