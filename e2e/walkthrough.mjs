// Records the product walkthrough: one lot from the catalogue to confirmed
// delivery, as a reseller and as the brand, with a caption for each step.
//
// Run it against the staging demo, freshly seeded:
//
//   docker compose -f docker-compose.prod.yml --env-file .env.staging exec api python -m khazana.seed --reset
//   cd e2e && node walkthrough.mjs
//
// The video is written to e2e/walkthrough/ as a .webm file. It is attached to
// each GitHub release rather than committed, because it is large and changes
// with every release. Captions are drawn inside the page, so no video tool is
// needed beyond the browser.

import { mkdirSync, readdirSync, renameSync } from "node:fs";

import { chromium } from "@playwright/test";

const WEB = process.env.WEB_URL ?? "https://localhost";
const API = process.env.API_URL ?? `${WEB}/api`;
const OUT = new URL("./walkthrough/", import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1");
const SIZE = { width: 1280, height: 800 };

mkdirSync(OUT, { recursive: true });

async function caption(page, text, ms = 3200) {
  await page.evaluate((words) => {
    let box = document.getElementById("walkthrough-caption");
    if (!box) {
      box = document.createElement("div");
      box.id = "walkthrough-caption";
      Object.assign(box.style, {
        position: "fixed",
        left: "50%",
        bottom: "28px",
        transform: "translateX(-50%)",
        maxWidth: "80%",
        padding: "14px 22px",
        background: "rgba(20, 64, 47, 0.94)",
        color: "#fff",
        font: "600 20px system-ui, sans-serif",
        borderRadius: "10px",
        zIndex: "99999",
        textAlign: "center",
      });
      document.body.appendChild(box);
    }
    box.textContent = words;
  }, text);
  await page.waitForTimeout(ms);
}

async function signIn(page, roleLabel) {
  await page.goto(`${WEB}/login`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: roleLabel }).click();
  const hint = page.getByText(/Development mode, your code is \d{6}/);
  await hint.waitFor();
  const code = (await hint.textContent()).match(/\d{6}/)[0];
  await page.getByLabel("Six digit code").fill(code);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  await page.waitForLoadState("networkidle");
}

async function lotToBuy(request) {
  const token = async (phone) => {
    const sent = await (await request.post(`${API}/auth/otp/request`, { data: { phone } })).json();
    const pair = await (
      await request.post(`${API}/auth/otp/verify`, { data: { phone, code: sent.dev_code } })
    ).json();
    return pair.access_token;
  };
  const brand = await token("03010000000");
  const lots = await (
    await request.get(`${API}/lots?status=live`, { headers: { Authorization: `Bearer ${brand}` } })
  ).json();
  const reseller = await token("03020000000");
  for (const lot of lots.items ?? lots) {
    const quote = await request.post(`${API}/orders/quote`, {
      headers: { Authorization: `Bearer ${reseller}` },
      data: { purchase: { lot_id: lot.id, whole_lot: true }, delivery_city: "Lahore" },
    });
    if (quote.ok()) return lot.id;
  }
  throw new Error("No live lot to buy. Reseed staging.");
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const context = await browser.newContext({
  viewport: SIZE,
  ignoreHTTPSErrors: true,
  recordVideo: { dir: OUT, size: SIZE },
});
const page = await context.newPage();
const lotId = await lotToBuy(context.request);

await page.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await caption(page, "Khazana Outlet: Pakistani brands' surplus stock, sold in bulk to verified resellers.", 4200);
await caption(page, "This is the public demo. Every brand, shop and order is sample data.");

await signIn(page, "A reseller buying stock");
await page.goto(`${WEB}/catalog`, { waitUntil: "networkidle" });
await caption(page, "A reseller sees the catalogue, with picks chosen for their shop and the reason for each.");
await page.mouse.wheel(0, 600);
await caption(page, "Every lot shows its grade, its discount off retail and the price per piece.");

await page.goto(`${WEB}/catalog/${lotId}`, { waitUntil: "networkidle" });
await caption(page, "A lot: photographs, the full manifest of sizes and colours, and declared defects.");
await page.mouse.wheel(0, 700);
await caption(page, "The profit helper works out the margin at the reseller's own selling price.");

await page.getByRole("button", { name: "Add to cart" }).click();
await page.waitForURL(/\/cart/);
await page.getByLabel("Delivery city").fill("Lahore");
await page.getByLabel("Full delivery address").fill("Shop 4, Azam Cloth Market");
await page.getByLabel("Pay with").selectOption("jazzcash");
await caption(page, "Checkout: delivery to the shop, paid by JazzCash, Easypaisa, card, bank transfer or cash.");
await page.getByRole("button", { name: "Place order" }).click();
await page.waitForURL(/\/orders\/[0-9a-f-]{36}/);
const orderUrl = new URL(page.url()).pathname;
await page.getByRole("button", { name: "Pay in the sandbox" }).click();
await page.getByText("Paid, held safely").waitFor();
await caption(page, "The payment is held by Khazana, not paid to the brand, until the goods arrive.", 4000);

await signIn(page, "A brand selling stock");
await page.goto(`${WEB}/dashboard`, { waitUntil: "networkidle" });
await caption(page, "The brand's dashboard: what is live, selling and waiting.");
await page.goto(`${WEB}${orderUrl}`, { waitUntil: "networkidle" });
await caption(page, "The brand books the courier; the label is generated and tracking updates the order.");
await page.getByRole("button", { name: "Book the courier" }).click();
const advance = page.getByRole("button", { name: "Move to next sandbox step" });
for (let step = 0; step < 3; step += 1) {
  await advance.click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
}
await caption(page, "Collected, in transit, delivered.");

await page.goto(`${WEB}/insights`, { waitUntil: "networkidle" });
await caption(page, "Brands can ask about their own stock in plain words. It answers from their data only.", 4000);

await signIn(page, "A reseller buying stock");
await page.goto(`${WEB}${orderUrl}`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: "Goods received correctly" }).click();
await page.getByText("Completed").first().waitFor();
await caption(page, "The reseller confirms the goods arrived, and only then is the brand paid.", 4200);
await caption(page, "AI drafts, suggests and flags throughout. People decide prices, approvals and money.", 4500);

await context.close();
await browser.close();

const recorded = readdirSync(OUT).filter((name) => name.endsWith(".webm") && name !== "walkthrough.webm");
if (recorded.length) renameSync(`${OUT}${recorded[recorded.length - 1]}`, `${OUT}walkthrough.webm`);
console.log(`walkthrough written to ${OUT}walkthrough.webm`);
