import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import path from "node:path";

function option(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const url = option("--url");
const sectionTitle = option("--section-title");
const timeoutMs = Number(option("--timeout-ms", "45000"));
const headed = process.argv.includes("--headed");
const browserChannel = process.env.SCOREPREDICT_BROWSER_CHANNEL || "msedge";
const failureDir = process.env.SCOREPREDICT_BROWSER_FAILURE_DIR || "";

if (!url || !sectionTitle) {
  throw new Error("--url and --section-title are required");
}

const browser = await chromium.launch({ channel: browserChannel, headless: !headed });
let page;
try {
  const context = await browser.newContext({
    locale: "en-US",
    timezoneId: "Europe/Paris",
    viewport: { width: 1440, height: 1000 },
  });
  page = await context.newPage();
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await page.waitForFunction(
    (expected) => document.body?.innerText.includes(expected),
    sectionTitle,
    { timeout: timeoutMs },
  );
  const pageText = await page.locator("body").innerText();
  const sportsEvents = await page.locator('script[type="application/ld+json"]').evaluateAll((scripts) => {
    const events = [];
    const visit = (value) => {
      if (Array.isArray(value)) {
        value.forEach(visit);
        return;
      }
      if (!value || typeof value !== "object") return;
      const types = Array.isArray(value["@type"]) ? value["@type"] : [value["@type"]];
      if (types.includes("SportsEvent")) events.push(value);
      if (value["@graph"]) visit(value["@graph"]);
    };
    for (const script of scripts) {
      try {
        visit(JSON.parse(script.textContent || "null"));
      } catch {
        // Un bloc JSON-LD sans rapport avec les matchs ne doit pas bloquer la collecte.
      }
    }
    return events;
  });
  process.stdout.write(JSON.stringify({ title: await page.title(), pageText, sportsEvents }));
} catch (error) {
  if (failureDir && page) {
    try {
      await mkdir(failureDir, { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const safeTitle = sectionTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      await page.screenshot({
        path: path.join(failureDir, `${stamp}-${safeTitle || "page"}.png`),
        fullPage: true,
      });
    } catch {
      // La capture est uniquement un diagnostic et ne doit pas masquer l'erreur initiale.
    }
  }
  throw error;
} finally {
  await browser.close();
}
