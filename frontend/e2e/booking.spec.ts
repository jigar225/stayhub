import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import type { Reservation } from "../src/booking/api";
const evidenceDir = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";
const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const iso = (date: Date) => date.toISOString().slice(0, 10);
async function capture(page: Page, name: string) {
  await mkdir(evidenceDir, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    if (width === 390 && (await page.locator("aside.host-sidebar").count()))
      await expect(page.locator("aside.host-sidebar")).toHaveCSS(
        "transform",
        "matrix(1, 0, 0, 1, -240, 0)",
      );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${evidenceDir}/m4-${name}-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
async function hostCredentials() {
  const env = await readFile(new URL("../../.env", import.meta.url), "utf8");
  const values = Object.fromEntries(
    env
      .split("\n")
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [
          line.slice(0, i),
          line.slice(i + 1).replace(/^['"]|['"]$/g, ""),
        ];
      }),
  );
  return {
    email: process.env.SEED_HOST_EMAIL ?? values.SEED_HOST_EMAIL,
    password: process.env.SEED_HOST_PASSWORD ?? values.SEED_HOST_PASSWORD,
  };
}
async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
}
async function signup(page: Page, returnPath?: string) {
  const email = `m4-browser-${Date.now()}-${randomBytes(4).toString("hex")}@example.com`;
  const password = randomBytes(18).toString("base64url");
  await page.goto(
    `/signup${returnPath ? `?returnTo=${encodeURIComponent(returnPath)}` : ""}`,
  );
  await page.getByLabel("Full name").fill("Booking Regression Guest");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const token = (await (await response).json()).access_token as string;
  await expect(page).toHaveURL(
    returnPath ? new RegExp("/checkout/") : /\/profile$/,
  );
  return token;
}
async function dates(page: Page, listing: string, offset = 0) {
  const start = 100 + Math.floor(Math.random() * 300) + offset;
  for (let i = 0; i < 35; i++) {
    const check_in = iso(new Date(Date.now() + (start + i * 6) * 86400000));
    const check_out = iso(
      new Date(Date.now() + (start + i * 6 + 5) * 86400000),
    );
    const r = await page.request.post("/api/v1/booking-quotes", {
      headers: { Origin: origin },
      data: { listing_id: listing, check_in, check_out, guests: 1 },
    });
    if (r.status() === 200) return { check_in, check_out, guests: "1" };
    if (r.status() !== 409)
      throw new Error(`Date selection failed with HTTP ${r.status()}`);
  }
  throw new Error("No isolated available five-night range found");
}
async function pay(
  page: Page,
  listing: string,
  selected: Record<string, string>,
  shot?: string,
) {
  await page.goto(`/checkout/${listing}?${new URLSearchParams(selected)}`);
  await expect(
    page.getByRole("heading", { name: "Simulated payment", exact: true }),
  ).toBeVisible();
  if (shot) await capture(page, shot);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/reservations") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Pay €/ }).click();
  const result = await response;
  expect(result.status()).toBe(201);
  const reservation = (await result.json()).reservation as Reservation;
  await expect(page).toHaveURL(new RegExp(`/trips/${reservation.id}$`));
  return reservation;
}
async function findRequest(page: Page, code: string) {
  await page.goto("/host/today");
  await expect(
    page.getByRole("heading", { name: "Today", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Reservation categories" }),
  ).toBeVisible();
  for (let i = 0; i < 100; i++) {
    const card = page.locator(".request-card").filter({ hasText: code });
    if (await card.count()) return card;
    const more = page.getByRole("button", { name: "Load more reservations" });
    if (!(await more.count())) break;
    await more.click();
    await expect(more).not.toHaveText("Loading…");
  }
  throw new Error(`Request ${code} missing from bounded host pages`);
}
test("real request acceptance, decline refund, instant unknown-outcome recovery and booked party access", async ({
  page,
  browser,
}) => {
  test.setTimeout(180000);
  const publicResponse = await page.request.get(
    "/api/v1/listings?destination=Lisbon&limit=100",
  );
  expect(publicResponse.status()).toBe(200);
  const listings = (await publicResponse.json()).items as {
    id: string;
    booking_mode: string;
    demo_label: string | null;
  }[];
  const request = listings.find(
    (item) => item.booking_mode === "request" && item.demo_label,
  );
  const instant = listings.find(
    (item) => item.booking_mode === "instant" && item.demo_label,
  );
  if (!request || !instant)
    throw new Error(
      "Published seeded Lisbon request and instant stays required",
    );
  const firstDates = await dates(page, request.id);
  const returnPath = `/checkout/${request.id}?${new URLSearchParams(firstDates)}`;
  await page.goto(`/stays/${request.id}?${new URLSearchParams(firstDates)}`);
  await page.getByRole("link", { name: "Reserve", exact: true }).click();
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(returnPath);
  const guestToken = await signup(page, returnPath);
  await expect(page.getByRole("button", { name: /^Pay €/ })).toBeVisible();
  const created = await pay(page, request.id, firstDates, "checkout");
  expect(created.state).toBe("pending");
  await expect(
    page.getByRole("heading", { name: "Your request is awaiting the host" }),
  ).toBeVisible();
  await expect(page.getByText(created.code, { exact: true })).toBeVisible();
  await page.goto("/trips?category=pending");
  await expect(page.getByText(created.code, { exact: true })).toBeVisible();
  await capture(page, "trips");
  const outsiderContext = await browser.newContext();
  const outsider = await outsiderContext.newPage();
  const outsiderToken = await signup(outsider);
  const enrolled = await outsider.request.post("/api/v1/me/host-role", {
    headers: { Origin: origin, Authorization: `Bearer ${outsiderToken}` },
  });
  expect(enrolled.status()).toBe(200);
  const denied = await outsider.request.post(
    `/api/v1/host/reservations/${created.id}/accept`,
    {
      headers: {
        Origin: origin,
        Authorization: `Bearer ${outsiderToken}`,
        "Idempotency-Key": randomBytes(16).toString("hex"),
      },
      data: {},
    },
  );
  expect(denied.status()).toBe(404);
  await outsider.goto(`/trips/${created.id}`);
  await expect(outsider.getByRole("alert")).toBeVisible();
  await outsiderContext.close();
  const hostContext = await browser.newContext();
  const host = await hostContext.newPage();
  const credentials = await hostCredentials();
  await login(host, credentials.email, credentials.password);
  const first = await findRequest(host, created.code);
  await capture(host, "today");
  await first.getByRole("button", { name: "Accept request" }).click();
  await expect(
    host.locator(".request-card").filter({ hasText: created.code }),
  ).toHaveCount(0);
  await page.goto(`/trips/${created.id}`);
  await expect(
    page.getByRole("heading", { name: "Your stay is confirmed" }),
  ).toBeVisible();
  const secondDates = await dates(page, request.id, 6);
  const declined = await pay(page, request.id, secondDates);
  const second = await findRequest(host, declined.code);
  await second.getByRole("button", { name: "Decline request" }).click();
  await second
    .getByLabel("Decline reason")
    .fill("Unavailable for this request");
  await second.getByRole("button", { name: "Confirm decline" }).click();
  await expect(
    host.locator(".request-card").filter({ hasText: declined.code }),
  ).toHaveCount(0);
  await page.goto(`/trips/${declined.id}`);
  await expect(
    page.getByRole("heading", { name: "Full refund", exact: true }),
  ).toBeVisible();
  const detail = await page.request.get(`/api/v1/reservations/${declined.id}`, {
    headers: { Authorization: `Bearer ${guestToken}` },
  });
  const refund = (await detail.json()).reservation as Reservation;
  expect(refund.state).toBe("declined");
  expect(refund.refund?.amount_minor).toBe(refund.payment.amount_minor);
  expect(refund.host_entitlement_minor).toBe(0);
  const reopened = await page.request.post("/api/v1/booking-quotes", {
    headers: { Origin: origin },
    data: { listing_id: request.id, ...secondDates, guests: 1 },
  });
  expect(reopened.status()).toBe(200);
  const instantDates = await dates(page, instant.id);
  await page.goto(
    `/checkout/${instant.id}?${new URLSearchParams(instantDates)}`,
  );
  await expect(page.getByRole("button", { name: /^Pay €/ })).toBeVisible();
  let completed: Reservation | null = null;
  const keys: string[] = [];
  await page.route("**/api/v1/reservations", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      completed = (await response.json()).reservation;
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: /^Pay €/ }).click();
  await expect(page.getByRole("alert")).toContainText("outcome is unresolved");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Retry original payment" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry original payment" }).click();
  await expect(page).toHaveURL(/\/trips\//);
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  expect(completed).not.toBeNull();
  const confirmed = completed as unknown as Reservation;
  expect(confirmed.state).toBe("confirmed");
  await expect(page.getByText(confirmed.code, { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem("stayhub-pay-submission-v1"),
    ),
  ).toBeNull();
  await capture(page, "confirmation");
  await page.reload();
  await expect(page.getByText(confirmed.code, { exact: true })).toBeVisible();
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(
    `${evidenceDir}/m4-booking-codes.json`,
    JSON.stringify(
      {
        accepted: { id: created.id, code: created.code },
        declined: {
          id: declined.id,
          code: declined.code,
          refund_minor: refund.refund?.amount_minor,
        },
        instant: {
          id: confirmed.id,
          code: confirmed.code,
          total_minor: confirmed.price.total_minor,
        },
        unknown_outcome_same_key: true,
      },
      null,
      2,
    ),
  );
  await hostContext.close();
});
