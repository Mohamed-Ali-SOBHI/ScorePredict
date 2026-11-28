// Read the regular-time 1N2 tables displayed by the French comparison site.
import { chromium } from "playwright-core";
import { writeFile, mkdir, rename } from "node:fs/promises";
import path from "node:path";

const root = "https://www.coteur.com";
const leagues = {
  Bundesliga: "/cotes/foot/allemagne/bundesliga-d1",
  EPL: "/cotes/foot/angleterre/premier-league",
  G1: "/cotes/foot/grece/super-league-2",
};

async function readLeague(context, league, address) {
  const page = await context.newPage();
  try {
    const response = await page.goto(root + address, {waitUntil: "domcontentloaded"});
    if (!response?.ok()) throw Error("HTTP " + response?.status());
    await page.locator(".match-row [data-eventdate], h1").first().waitFor();
    const fixtures = await page.locator(".match-row").evaluateAll(rows => rows.flatMap(row => {
      const group = row.querySelector("[data-eventdate]");
      const link = row.querySelector("a[href^='/cote/']");
      if (!group || !link) return [];
      const kickoff = Number(group.dataset.eventdate) * 1000;
      const until = kickoff - Date.now();
      if (!(until >= 5 * 60000 && until <= 24 * 3600000 + 5 * 60000)) return [];
      const home = group.querySelector('[data-type="1n2"][data-choice="1"]')?.dataset.choicetxt;
      const away = group.querySelector('[data-type="1n2"][data-choice="2"]')?.dataset.choicetxt;
      const href = link.getAttribute("href");
      return home && away && /^\/cote\/[\w-]+-\d+$/.test(href) ? [{home,away,href,kickoff}] : [];
    }));
    return fixtures.map(f => ({...f,league}));
  } finally { await page.close(); }
}

async function readOffers(context, fixture) {
  const page = await context.newPage();
  try {
    const response = await page.goto(root + fixture.href, {waitUntil: "domcontentloaded"});
    if (!response?.ok() || new URL(page.url()).pathname !== fixture.href) throw Error("page inattendue");
    await page.locator("#oddslist tbody tr .cotes-col-book").first().waitFor({timeout: 12000});
    const offers = await page.evaluate(({home,away,kickoff}) => {
      const clock = document.querySelector(".match-duel-heure")?.dateTime;
      const market = document.querySelector('.cotes-puce[aria-pressed="true"]')?.dataset.oddsFilterTypeParam;
      const period = document.querySelector('.cotes-periode [aria-pressed="true"]')?.textContent.trim();
      if (Date.parse(clock) !== kickoff || kickoff <= Date.now() || market !== "1n2" || period !== "Match") return [];
      return Array.from(document.querySelectorAll("#oddslist tbody tr")).flatMap(row => {
        const history = row.querySelector("[data-historique-type-param]")?.dataset;
        if (!history || history.historiqueTypeParam !== "1n2" || history.historiqueEqudomParam !== home ||
            history.historiqueEquextParam !== away || history.historiqueHandicapParam ||
            row.querySelector(".cotes-suspendue") || row.classList.contains("cotes-ligne-suspendue")) return [];
        const book = row.querySelector(".cotes-col-book img")?.alt?.trim();
        if (!book) return [];
        const prices = {};
        for (const [key, choice] of [["home_win","1"],["draw","0"],["away_win","2"]]) {
          const cell = row.querySelector('a[data-odds-rencontre-choice-param="' + choice + '"]');
          const odds = Number(cell?.querySelector(".odd-value")?.textContent.trim().replace(",", "."));
          if (cell && !cell.matches('[aria-disabled="true"], .disabled') && Number.isFinite(odds) && odds > 1) prices[key] = odds;
        }
        return Object.keys(prices).length ? [{book,prices}] : [];
      });
    },fixture);
    return {...fixture,kickoff:new Date(fixture.kickoff).toISOString(),at:new Date().toISOString(),offers};
  } finally { await page.close(); }
}

const target = process.argv[2];
if (!target) throw Error("Chemin du relevé manquant");
const browser = await chromium.launch({channel: process.env.SCOREPREDICT_BROWSER_CHANNEL || "msedge", headless:true});
try {
  const context = await browser.newContext({locale:"fr-FR",timezoneId:"Europe/Paris"});
  context.setDefaultNavigationTimeout(20000);
  const jobs = [];
  const records = [];
  for (const [league,address] of Object.entries(leagues)) {
    try { jobs.push(...await readLeague(context,league,address)); }
    catch (err) { console.warn("Comparateur",league,String(err).split("\n")[0]); }
  }
  async function worker() {
    while (jobs.length) {
      const f=jobs.shift();
      try { records.push(await readOffers(context,f)); }
      catch (err) { console.warn("Comparateur",f.href,String(err).split("\n")[0]); }
    }
  }
  await Promise.all([worker(),worker(),worker()]);
  await mkdir(path.dirname(target),{recursive:true});
  const temp = target + "." + process.pid + ".tmp";
  await writeFile(temp,JSON.stringify({capturedAt:new Date().toISOString(),records}));
  await rename(temp,target);
  console.log("Comparateur 1N2 :",records.filter(r=>r.offers.length).length,"matchs avec des cotes nominatives.");
} finally { await browser.close(); }
