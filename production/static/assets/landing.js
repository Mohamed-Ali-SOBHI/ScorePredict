document.documentElement.classList.add("js");

const $ = (selector, root = document) => root.querySelector(selector);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const integer = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signedPercent = new Intl.NumberFormat("fr-FR", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function numberOrNull(value) {
  if (value === null || value === "" || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function validText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function validDate(value) {
  return validText(value) && !Number.isNaN(new Date(value).getTime());
}

function validPrediction(prediction) {
  if (!isObject(prediction)) return false;
  const odds = numberOrNull(prediction.odds);
  const probability = numberOrNull(prediction.modelProbability);
  const stake = numberOrNull(prediction.stakeEur);
  return prediction.recommended === true
    && validText(prediction.homeTeam)
    && validText(prediction.awayTeam)
    && prediction.homeTeam.trim() !== prediction.awayTeam.trim()
    && validText(prediction.outcomeLabel)
    && validDate(prediction.date)
    && odds !== null && odds > 1 && odds <= 100
    && probability !== null && probability > 0 && probability <= 1
    && stake !== null && stake > 0 && stake <= 10000;
}

function validPayload(data) {
  if (!isObject(data) || !isObject(data.meta) || !isObject(data.summary)) return false;
  const examined = numberOrNull(data.summary.scoredFixtures);
  const expected = numberOrNull(data.summary.upcomingBets);
  return validDate(data.meta.generatedAt)
    && validText(data.meta.status)
    && Number.isInteger(examined) && examined >= 0
    && Number.isInteger(expected) && expected >= 0 && expected <= 100
    && Array.isArray(data.predictions)
    && data.predictions.length === expected
    && data.predictions.every(validPrediction);
}

async function fetchDashboard() {
  const canUseApi = /^https?:$/.test(window.location.protocol)
    && !window.location.hostname.endsWith(".github.io");

  if (canUseApi) {
    try {
      const response = await fetch("/api/v1/dashboard", {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (response.ok && (response.headers.get("content-type") || "").includes("application/json")) {
        const data = await response.json();
        if (validPayload(data)) return data;
      }
    } catch {
      // Le fichier public prend le relais quand l'API locale n'est pas disponible.
    }
  }

  const response = await fetch(`./data/dashboard.json?v=${Date.now()}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("Journal public indisponible");
  const data = await response.json();
  if (!validPayload(data)) throw new Error("Journal public incomplet");
  return data;
}

function parseDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value, includeTime = false) {
  const date = parseDate(value);
  if (!date) return "date à confirmer";
  const options = includeTime
    ? { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "long", year: "numeric" };
  return new Intl.DateTimeFormat("fr-FR", options).format(date);
}

function firstNumber(...values) {
  for (const value of values) {
    const number = numberOrNull(value);
    if (number !== null) return number;
  }
  return null;
}

function countText(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : integer.format(Math.max(0, Math.trunc(number)));
}

function percentText(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : signedPercent.format(number);
}

function renderTracking(data) {
  const tracking = isObject(data.tracking) ? data.tracking : {};
  const live = isObject(data.performance?.live) ? data.performance.live : {};
  const pending = firstNumber(tracking.pending, data.summary.pendingPredictions, data.summary.upcomingBets) ?? 0;
  const settled = firstNumber(tracking.verified, data.summary.settledLiveBets, live.settledBets) ?? 0;
  const won = firstNumber(tracking.won, data.summary.wonPredictions, live.wonBets) ?? 0;
  const lost = firstNumber(tracking.lost, data.summary.lostPredictions) ?? 0;
  const liveReturn = firstNumber(live.roi, data.summary.liveRoi);

  setText("#live-pending", countText(pending));
  setText("#live-settled", countText(settled));
  setText("#live-won", countText(won));
  setText("#live-lost", countText(lost));

  if (settled <= 0 || liveReturn === null) {
    setText("#live-return", "Non calculable");
    setText("#live-explanation", "Pas encore assez de résultats terminés pour calculer un rendement réel.");
  } else {
    setText("#live-return", percentText(liveReturn));
    setText("#live-explanation", `Calcul établi sur ${integer.format(settled)} pari${settled > 1 ? "s" : ""} terminé${settled > 1 ? "s" : ""}.`);
  }

  const storageReady = tracking.storageReady === true;
  $("#memory-state")?.classList.toggle("ready", storageReady);
  setText("#memory-title", storageReady ? "Historique permanent actif" : "Historique permanent en attente");
  setText(
    "#storage-copy",
    storageReady
      ? "Les décisions et leurs résultats sont conservés dans la mémoire en ligne."
      : "Le journal fonctionne, mais la mémoire en ligne n’est pas signalée comme active dans cette publication.",
  );
}

function renderPastTests(data) {
  const performance = isObject(data.performance) ? data.performance : {};
  const metrics = isObject(performance.metrics) ? performance.metrics : {};
  const scope = isObject(performance.scope) ? performance.scope : {};
  const betCount = firstNumber(metrics.betCount, data.summary.testBets);
  const observed = firstNumber(metrics.roi, data.summary.testRoi);
  const low = firstNumber(metrics.roiCiLow);
  const high = firstNumber(metrics.roiCiHigh);
  const drawdown = firstNumber(metrics.maxDrawdown, data.summary.maxDrawdown);

  setText("#test-count", countText(betCount));
  setText("#test-return", percentText(observed));
  setText("#test-range", low === null || high === null ? "Non disponible" : `${percentText(low)} à ${percentText(high)}`);
  setText("#test-drawdown", drawdown === null ? "Non disponible" : `${decimal.format(Math.abs(drawdown))} mises`);

  if (validDate(scope.startDate) && validDate(scope.endDate)) {
    setText("#test-period", `${formatDate(scope.startDate)} — ${formatDate(scope.endDate)}`);
  } else {
    setText("#test-period", "Saisons 2022 — 2026");
  }

  setText("#range-low", percentText(low));
  setText("#range-high", percentText(high));
  setText("#range-observed", observed === null ? "—" : `${percentText(observed)} observé`);
  setText(
    "#drawdown-line",
    drawdown === null ? "Plus forte baisse non disponible" : `Plus forte baisse : ${decimal.format(Math.abs(drawdown))} mises`,
  );

  if (low !== null && high !== null && high > low) {
    const marker = observed === null ? 50 : ((observed - low) / (high - low)) * 100;
    const zero = ((0 - low) / (high - low)) * 100;
    const rangeTrack = $("#range-track");
    rangeTrack?.style.setProperty("--range-position", `${Math.min(100, Math.max(0, marker)).toFixed(2)}%`);
    rangeTrack?.style.setProperty("--zero-position", `${Math.min(100, Math.max(0, zero)).toFixed(2)}%`);
  }
}

function render(data) {
  const loadError = $("#load-error");
  if (loadError) loadError.hidden = true;
  renderTracking(data);
  renderPastTests(data);
}

function renderError() {
  setText("#memory-title", "État non vérifié");
  setText("#storage-copy", "La mémoire ne peut pas être confirmée sans les données du journal.");
  setText("#live-explanation", "Les résultats réels sont momentanément indisponibles.");
  const loadError = $("#load-error");
  if (loadError) {
    loadError.textContent = "Le journal est momentanément indisponible.";
    loadError.hidden = false;
  }
}

async function load() {
  try {
    const data = await fetchDashboard();
    render(data);
  } catch (error) {
    console.error("Impossible de lire le journal public", error);
    renderError();
  }
}

function setupReveal() {
  const elements = [...document.querySelectorAll("[data-reveal]")];
  if (reducedMotion.matches || !("IntersectionObserver" in window)) {
    elements.forEach((element) => element.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    });
  }, { threshold: .14, rootMargin: "0px 0px -7%" });
  elements.forEach((element) => observer.observe(element));
}

const rivalryMatches = Object.freeze([
  { competition: "Espagne", home: "FC Barcelone", away: "Real Madrid", label: "El Clásico" },
  { competition: "Angleterre", home: "Liverpool", away: "Manchester City", label: "Le choc d’Angleterre" },
  { competition: "Italie", home: "Inter Milan", away: "AC Milan", label: "Derby della Madonnina" },
  { competition: "France", home: "Paris SG", away: "Marseille", label: "Le Classique" },
  { competition: "Allemagne", home: "Bayern Munich", away: "Dortmund", label: "Der Klassiker" },
  { competition: "Angleterre", home: "Arsenal", away: "Chelsea", label: "Derby de Londres" },
]);

function setupRivalryCarousel() {
  const wrap = $("#hero-object-wrap");
  const slide = $("#rivalry-slide");
  const dots = [...document.querySelectorAll("#carousel-dots button")];
  const previous = $("#carousel-prev");
  const next = $("#carousel-next");
  const pause = $("#carousel-pause");
  const announcement = $("#carousel-announcement");
  if (!wrap || !slide || dots.length !== rivalryMatches.length) return;

  let index = 0;
  let timer = 0;
  let pausedByUser = false;

  function stop() {
    window.clearTimeout(timer);
    timer = 0;
  }

  function interactionPaused() {
    return document.hidden || wrap.matches(":hover") || wrap.contains(document.activeElement);
  }

  function schedule() {
    stop();
    if (reducedMotion.matches || pausedByUser || interactionPaused()) return;
    timer = window.setTimeout(() => show(index + 1, false), 4200);
  }

  function reflectPauseButton() {
    if (!pause) return;
    const reduced = reducedMotion.matches;
    pause.disabled = reduced;
    pause.setAttribute("aria-pressed", String(reduced || pausedByUser));
    pause.setAttribute(
      "aria-label",
      reduced
        ? "Défilement automatique désactivé par vos préférences d’animation"
        : pausedByUser
          ? "Relancer le carrousel"
          : "Mettre le carrousel en pause",
    );
    const symbol = $("span", pause);
    if (symbol) symbol.textContent = pausedByUser ? "▶" : "Ⅱ";
  }

  function show(nextIndex, announce) {
    index = (nextIndex + rivalryMatches.length) % rivalryMatches.length;
    const match = rivalryMatches[index];
    setText("#object-context", match.competition);
    setText("#object-primary", match.home);
    setText("#object-secondary", match.away);
    setText("#object-detail", match.label);
    setText("#carousel-count", `${String(index + 1).padStart(2, "0")} / ${String(rivalryMatches.length).padStart(2, "0")}`);
    const progress = $("#carousel-progress");
    if (progress) progress.style.width = `${((index + 1) / rivalryMatches.length) * 100}%`;
    dots.forEach((dot, dotIndex) => {
      if (dotIndex === index) dot.setAttribute("aria-current", "true");
      else dot.removeAttribute("aria-current");
    });

    slide.classList.remove("is-changing");
    void slide.offsetWidth;
    slide.classList.add("is-changing");
    if (announce && announcement) {
      announcement.textContent = `${match.home} contre ${match.away}, ${match.label}.`;
    }
    schedule();
  }

  previous?.addEventListener("click", () => show(index - 1, true));
  next?.addEventListener("click", () => show(index + 1, true));
  dots.forEach((dot, dotIndex) => dot.addEventListener("click", () => show(dotIndex, true)));
  pause?.addEventListener("click", () => {
    pausedByUser = !pausedByUser;
    reflectPauseButton();
    if (pausedByUser) stop();
    else schedule();
  });

  wrap.addEventListener("pointerenter", stop);
  wrap.addEventListener("pointerleave", schedule);
  wrap.addEventListener("focusin", stop);
  wrap.addEventListener("focusout", () => window.setTimeout(schedule, 0));
  document.addEventListener("visibilitychange", () => document.hidden ? stop() : schedule());
  reducedMotion.addEventListener?.("change", () => {
    reflectPauseButton();
    schedule();
  });

  reflectPauseButton();
  show(0, false);
}

const root = document.documentElement;
const objectWrap = $("#hero-object-wrap");
let pointerFrame = 0;

function resetTilt() {
  root.style.setProperty("--tilt-x", "5deg");
  root.style.setProperty("--tilt-y", "-8deg");
}

objectWrap?.addEventListener("pointermove", (event) => {
  if (reducedMotion.matches || event.pointerType === "touch") return;
  const bounds = objectWrap.getBoundingClientRect();
  const x = Math.max(-1, Math.min(1, ((event.clientX - bounds.left) / bounds.width - .5) * 2));
  const y = Math.max(-1, Math.min(1, ((event.clientY - bounds.top) / bounds.height - .5) * 2));
  if (!pointerFrame) {
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      root.style.setProperty("--tilt-x", `${(5 - y * 4).toFixed(2)}deg`);
      root.style.setProperty("--tilt-y", `${(-8 + x * 8).toFixed(2)}deg`);
    });
  }
});
objectWrap?.addEventListener("pointerleave", resetTilt);
objectWrap?.addEventListener("pointercancel", resetTilt);

const topbar = $("#topbar");
const hero = $("#journal");
let scrollFrame = 0;
function onScroll() {
  if (scrollFrame) return;
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0;
    topbar?.classList.toggle("scrolled", window.scrollY > 12);
    if (reducedMotion.matches) return;
    const bounds = hero?.getBoundingClientRect();
    const progress = bounds ? Math.min(1, Math.max(0, -bounds.top / Math.max(1, bounds.height))) : 0;
    root.style.setProperty("--object-shift", `${(progress * 24).toFixed(1)}px`);
  });
}

window.addEventListener("scroll", onScroll, { passive: true });
window.addEventListener("resize", onScroll, { passive: true });
reducedMotion.addEventListener?.("change", () => {
  resetTilt();
  root.style.setProperty("--object-shift", "0px");
});

setText("#year", String(new Date().getFullYear()));
setupReveal();
setupRivalryCarousel();
onScroll();
load();
setInterval(load, 5 * 60 * 1000);
