import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const listing = "975a5b9c-b000-5f01-b9aa-2a8f9d369ec4";
const evidence = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";
for (const width of [390, 768, 1024, 1440]) {
  test(`integrated responsive controls ${width}`, async ({ page }) => {
    await mkdir(evidence, { recursive: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto(`/stays/${listing}`);
    await expect(
      page.getByRole("heading", { name: "Where you’ll be" }),
    ).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect
      .poll(() =>
        page
          .locator(".public-gallery img")
          .evaluateAll((images) =>
            images.every(
              (img) =>
                (img as HTMLImageElement).complete &&
                (img as HTMLImageElement).naturalWidth > 0,
            ),
          ),
      )
      .toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (width === 768 || width === 1024) {
      const content = await page
        .locator(".public-detail-columns > div")
        .boundingBox();
      expect(content!.width).toBeGreaterThan(width - 160);
    }
    await page.screenshot({
      path: `${evidence}/detail-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: /Show all.*photos/ }).click();
    const viewer = page.getByRole("dialog", { name: /photos/i });
    await expect(viewer).toBeVisible();
    await page.screenshot({ path: `${evidence}/photo-viewer-${width}.png` });
    await viewer.press("ArrowRight");
    await viewer.press("Escape");
    await expect(viewer).not.toBeVisible();
    await page.getByRole("button", { name: "Check in", exact: true }).click();
    const dates = page.getByRole("dialog", { name: "Choose travel dates" });
    await expect(dates).toBeVisible();
    const bounds = await dates.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: `${evidence}/dates-${width}.png` });
    await dates.press("Escape");
    await page.goto("/stays");
    await page.getByRole("button", { name: /Filters/ }).click();
    const filters = page.getByRole("dialog", { name: "Filters", exact: true });
    await expect(filters).toBeVisible();
    await page.screenshot({ path: `${evidence}/filters-${width}.png` });
    await filters.press("Escape");
  });
}
test("short photo viewer and long detail content", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 480 });
  await page.route(`**/api/v1/listings/${listing}`, async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.listing.title =
      "A long genuine host-entered title used to inspect wrapping and readable tablet controls";
    await route.fulfill({ response, json });
  });
  await page.goto(`/stays/${listing}`);
  await page.getByRole("button", { name: /Show all.*photos/ }).click();
  const viewer = page.getByRole("dialog", { name: /photos/i });
  await expect(viewer).toBeVisible();
  const bounds = await viewer.boundingBox();
  expect(bounds!.height).toBeLessThanOrEqual(480);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  await page.screenshot({ path: `${evidence}/viewer-short-768.png` });
  await viewer.press("Escape");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("host location controls and category labels at release widths", async ({
  page,
}) => {
  const login = await page.request.post("/api/v1/auth/login", {
    headers: { Origin: process.env.SMOKE_BASE_URL ?? "http://localhost:5173" },
    data: {
      email: process.env.SEED_HOST_EMAIL,
      password: process.env.SEED_HOST_PASSWORD,
    },
  });
  expect(login.status()).toBe(200);
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto(`/host/listings/${listing}/edit`);
    await expect(
      page.getByRole("combobox", { name: "Street address" }),
    ).toBeVisible();
    await expect(page.getByLabel("Latitude", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Longitude", { exact: true })).toBeVisible();
    const label = page.locator(".listing-category-option").first();
    const box = await label.boundingBox();
    const checkbox = await label.locator("input").boundingBox();
    expect(checkbox!.y + checkbox!.height / 2).toBeGreaterThan(box!.y);
    expect(checkbox!.y + checkbox!.height / 2).toBeLessThan(
      box!.y + box!.height,
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${evidence}/host-location-${width}.png`,
      fullPage: true,
    });
    await page.goto("/host/today");
    await expect(
      page.getByRole("heading", { name: "Arriving today", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "View arrivals", exact: true })
      .click();
    await page.screenshot({
      path: `${evidence}/host-arrivals-${width}.png`,
      fullPage: true,
    });
  }
});

test("real booked trip photos and summaries at release widths", async ({
  page,
}) => {
  const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
  const login = await page.request.post("/api/v1/auth/login", {
    headers: { Origin: origin },
    data: {
      email: process.env.SEED_GUEST_EMAIL,
      password: process.env.SEED_GUEST_PASSWORD,
    },
  });
  expect(login.status()).toBe(200);
  const token = (await login.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}`, Origin: origin };
  const clock = await (await page.request.get("/api/v1/business-time")).json();
  let quoteToken = "";
  for (let offset = 180; offset < 260; offset += 7) {
    const start = new Date(clock.business_now);
    start.setUTCDate(start.getUTCDate() + offset);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 2);
    const quote = await page.request.post("/api/v1/booking-quotes", {
      data: {
        listing_id: listing,
        check_in: start.toISOString().slice(0, 10),
        check_out: end.toISOString().slice(0, 10),
        guests: 1,
      },
    });
    if (quote.status() === 409) continue;
    expect(quote.status()).toBe(200);
    quoteToken = (await quote.json()).quote.quote_token;
    break;
  }
  expect(quoteToken).toBeTruthy();
  const paid = await page.request.post("/api/v1/reservations", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { quote_token: quoteToken },
  });
  expect(paid.status()).toBe(201);
  const reservation = (await paid.json()).reservation;
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto("/trips?category=upcoming");
    const card = page
      .locator(".trip-card")
      .filter({ hasText: reservation.code });
    await expect(card).toBeVisible();
    await expect(card.locator(".trip-card-photo img")).toBeVisible();
    await expect
      .poll(() =>
        card
          .locator("img")
          .evaluate(
            (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
          ),
      )
      .toBe(true);
    await expect(card).toContainText("Original total");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${evidence}/trips-${width}.png`,
      fullPage: true,
    });
  }
});
