import { writeFileSync } from "node:fs";

import { expect, test, type APIRequestContext, type Browser } from "@playwright/test";

/**
 * How the main pages load for a reseller on a slow connection and a mid range
 * phone: Chrome DevTools' Regular 3G profile (750 kbit/s down, 250 up, 300 ms
 * latency) and the CPU slowed four times. Every page loads with an empty
 * cache, in a fresh browser context, as a first visit.
 *
 * Measured per page: Largest Contentful Paint, the time until the page's own
 * heading is on screen, bytes over the network, and request count.
 */

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const NETWORK = {
  offline: false,
  latency: 300,
  downloadThroughput: (750 * 1024) / 8,
  uploadThroughput: (250 * 1024) / 8,
};
const CPU_SLOWDOWN = 4;

type Result = {
  page: string;
  lcpMs: number;
  readyMs: number;
  kilobytes: number;
  scriptKilobytes: number;
  imageKilobytes: number;
  requests: number;
};

const tokens = new Map<string, { access_token: string; refresh_token: string }>();

async function signIn(request: APIRequestContext, phone: string) {
  const cached = tokens.get(phone);
  if (cached) return cached;
  const sent = await request.post(`${API_URL}/auth/otp/request`, { data: { phone } });
  expect(sent.ok(), await sent.text()).toBeTruthy();
  const verified = await request.post(`${API_URL}/auth/otp/verify`, {
    data: { phone, code: (await sent.json()).dev_code },
  });
  const pair = await verified.json();
  tokens.set(phone, pair);
  return pair;
}

async function measure(
  browser: Browser,
  device: object,
  name: string,
  path: string,
  pair: { access_token: string; refresh_token: string } | null,
): Promise<Result> {
  const context = await browser.newContext(device);
  if (pair) {
    await context.addInitScript(([access, refresh]) => {
      sessionStorage.setItem("khazana.access", access);
      sessionStorage.setItem("khazana.refresh", refresh);
    }, [pair.access_token, pair.refresh_token]);
  }
  await context.addInitScript(() => {
    (window as unknown as { __lcp: number }).__lcp = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        (window as unknown as { __lcp: number }).__lcp = entry.startTime;
      }
    }).observe({ type: "largest-contentful-paint", buffered: true });
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", NETWORK);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU_SLOWDOWN });

  const types = new Map<string, string>();
  let bytes = 0;
  let scriptBytes = 0;
  let imageBytes = 0;
  let requests = 0;
  cdp.on("Network.responseReceived", (event) => types.set(event.requestId, event.type));
  cdp.on("Network.loadingFinished", (event) => {
    requests += 1;
    bytes += event.encodedDataLength;
    const type = types.get(event.requestId);
    if (type === "Script") scriptBytes += event.encodedDataLength;
    if (type === "Image" || type === "Fetch") {
      // Photos arrive by fetch, because they need a bearer token.
      if (type === "Image") imageBytes += event.encodedDataLength;
    }
  });
  cdp.on("Network.responseReceived", (event) => {
    if (event.response.mimeType.startsWith("image/")) types.set(event.requestId, "Image");
  });

  const started = Date.now();
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.locator("h1").first()).toBeVisible({ timeout: 120_000 });
  const readyMs = Date.now() - started;
  await page.waitForLoadState("networkidle", { timeout: 120_000 });
  const lcpMs = await page.evaluate(() => (window as unknown as { __lcp: number }).__lcp);
  await context.close();
  return {
    page: name,
    lcpMs: Math.round(lcpMs),
    readyMs,
    kilobytes: Math.round(bytes / 1024),
    scriptKilobytes: Math.round(scriptBytes / 1024),
    imageKilobytes: Math.round(imageBytes / 1024),
    requests,
  };
}

test("main pages on Regular 3G and a 4x slower CPU", async ({ browser, request, playwright }) => {
  const device = playwright.devices["Pixel 7"];
  const reseller = await signIn(request, "03020000000");
  const brand = await signIn(request, "03010000000");
  const catalog = await request.get(`${API_URL}/catalog?limit=1`, {
    headers: { Authorization: `Bearer ${reseller.access_token}` },
  });
  const lotId = (await catalog.json()).items[0].lot.id;

  const pages: [string, string, typeof reseller | null][] = [
    ["Login", "/login", null],
    ["Catalogue", "/catalog", reseller],
    ["Lot", `/catalog/${lotId}`, reseller],
    ["Orders", "/orders", reseller],
    ["Brand dashboard", "/dashboard", brand],
    ["Brand lots", "/lots", brand],
  ];
  const results: Result[] = [];
  for (const [name, path, pair] of pages) {
    results.push(await measure(browser, device, name, path, pair));
  }
  console.table(results);
  writeFileSync("perf-results.json", JSON.stringify(results, null, 2));
});
