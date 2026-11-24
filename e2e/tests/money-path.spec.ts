import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

/**
 * The money path, the way the three people involved actually do it.
 *
 * A reseller buys a whole lot and pays in the sandbox. The brand books the
 * courier and the courier reports each step. The reseller confirms the goods
 * arrived. Every step goes through the real web app on a phone sized screen,
 * against the real API and database, with no shortcut through the API except
 * to choose which lot to buy.
 *
 * Seeded accounts: the reseller is 03020000000 and the brand owner is
 * 03010000000. Each run buys one lot, so reseed between runs if the brand runs
 * out of live lots.
 */

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const RESELLER = "03020000000";
const BRAND = "03010000000";

// One code per phone per run: the API allows five an hour per number.
const tokens = new Map<string, string>();

async function apiToken(request: APIRequestContext, phone: string): Promise<string> {
  const cached = tokens.get(phone);
  if (cached) return cached;
  const sent = await request.post(`${API_URL}/auth/otp/request`, { data: { phone } });
  expect(sent.ok(), await sent.text()).toBeTruthy();
  const { dev_code: code } = await sent.json();
  expect(code, "OTP_DEV_ECHO must be on for the e2e stack").toBeTruthy();
  const verified = await request.post(`${API_URL}/auth/otp/verify`, { data: { phone, code } });
  expect(verified.ok(), await verified.text()).toBeTruthy();
  const token: string = (await verified.json()).access_token;
  tokens.set(phone, token);
  return token;
}

/** A live lot of the seeded brand that the seeded reseller may buy whole. */
async function lotToBuy(request: APIRequestContext): Promise<{ id: string; code: string }> {
  const brandToken = await apiToken(request, BRAND);
  const mine = await request.get(`${API_URL}/lots?status=live`, {
    headers: { Authorization: `Bearer ${brandToken}` },
  });
  expect(mine.ok(), await mine.text()).toBeTruthy();
  const body = await mine.json();
  const lots: { id: string; lot_code: string; reserved_pieces?: number }[] = body.items ?? body;

  const resellerToken = await apiToken(request, RESELLER);
  for (const lot of lots) {
    if (lot.reserved_pieces) continue;
    const quote = await request.post(`${API_URL}/orders/quote`, {
      headers: { Authorization: `Bearer ${resellerToken}` },
      data: { purchase: { lot_id: lot.id, whole_lot: true }, delivery_city: "Lahore" },
    });
    if (quote.ok()) return { id: lot.id, code: lot.lot_code };
  }
  throw new Error("The seeded brand has no live lot this reseller can buy. Reseed the stack.");
}

async function signIn(page: Page, phone: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  const hint = page.getByText(/Development mode, your code is \d{6}/);
  await expect(hint).toBeVisible();
  const code = (await hint.textContent())?.match(/\d{6}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel("Six digit code").fill(code as string);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function asPerson(browser: Browser, phone: string, device: object): Promise<Page> {
  const context = await browser.newContext(device);
  const page = await context.newPage();
  await signIn(page, phone);
  return page;
}

test("a lot travels from checkout to confirmed delivery", async ({
  browser,
  request,
  playwright,
}) => {
  const phone = playwright.devices["Pixel 7"];
  const lot = await lotToBuy(request);

  // The reseller adds the whole lot to the cart and places the order.
  const reseller = await asPerson(browser, RESELLER, phone);
  await reseller.goto(`/catalog/${lot.id}`);
  await reseller.getByRole("button", { name: "Add to cart" }).click();
  await expect(reseller).toHaveURL(/\/cart/);
  await reseller.getByLabel("Delivery city").fill("Lahore");
  await reseller.getByLabel("Full delivery address").fill("Shop 4, Azam Cloth Market");
  await reseller.getByLabel("Pay with").selectOption("jazzcash");
  await reseller.getByRole("button", { name: "Place order" }).click();
  await expect(reseller).toHaveURL(/\/orders\/[0-9a-f-]{36}/);
  const orderUrl = new URL(reseller.url()).pathname;

  // The reseller pays in the sandbox, and the money is held, not released.
  await reseller.getByRole("button", { name: "Pay in the sandbox" }).click();
  await expect(reseller.getByText("Paid, held safely")).toBeVisible();

  // The brand books the courier and moves it through each sandbox step.
  const brand = await asPerson(browser, BRAND, phone);
  await brand.goto(orderUrl);
  await brand.getByRole("button", { name: "Book the courier" }).click();
  const advance = brand.getByRole("button", { name: "Move to next sandbox step" });
  for (let step = 0; step < 3; step += 1) {
    await expect(advance).toBeEnabled();
    await advance.click();
    await brand.waitForLoadState("networkidle");
  }
  await expect(advance).toHaveCount(0);

  // The reseller confirms, which completes the order and releases the money.
  await reseller.reload();
  await reseller.getByRole("button", { name: "Goods received correctly" }).click();
  await expect(reseller.getByText("Completed").first()).toBeVisible();
  await expect(reseller.getByRole("button", { name: "Goods received correctly" })).toHaveCount(0);

  await reseller.context().close();
  await brand.context().close();
});

test("another reseller cannot open someone else's order", async ({ browser, request, playwright }) => {
  const phone = playwright.devices["Pixel 7"];
  const resellerToken = await apiToken(request, RESELLER);
  const orders = await request.get(`${API_URL}/orders`, {
    headers: { Authorization: `Bearer ${resellerToken}` },
  });
  const mine: { id: string }[] = await orders.json();
  test.skip(mine.length === 0, "the seeded reseller has no orders yet");

  // The second seeded reseller.
  const other = await asPerson(browser, "03020000001", phone);
  await other.goto(`/orders/${mine[0].id}`);
  await expect(other.getByText(/does not exist|not found/i)).toBeVisible();
  await other.context().close();
});
