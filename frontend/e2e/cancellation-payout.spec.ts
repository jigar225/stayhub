import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import type { Reservation } from "../src/booking/api";
const origin = process.env.SMOKE_BASE_URL ?? "";
const iso = (date: Date) => date.toISOString().slice(0, 10);
async function capture(page: Page, name: string) {
  await mkdir("evidence", { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    if (
      width === 390 &&
      !page.url().endsWith("/admin") &&
      (await page.locator("aside.host-sidebar").count())
    )
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
      path: `evidence/m5-${name}-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
async function credentials(role: "HOST" | "ADMIN") {
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
    email: process.env[`SEED_${role}_EMAIL`] ?? values[`SEED_${role}_EMAIL`],
    password:
      process.env[`SEED_${role}_PASSWORD`] ?? values[`SEED_${role}_PASSWORD`],
  };
}
async function login(page: Page, role: "HOST" | "ADMIN") {
  const c = await credentials(role);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(c.email);
  await page.getByLabel("Password", { exact: true }).fill(c.password);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  const token = (await (await response).json()).access_token as string;
  await expect(page).toHaveURL(/\/profile$/);
  return token;
}
async function signup(page: Page) {
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("Cancellation Review Guest");
  await page
    .getByLabel("Email address")
    .fill(`m5-${Date.now()}-${randomBytes(4).toString("hex")}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill(randomBytes(18).toString("base64url"));
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const token = (await (await response).json()).access_token as string;
  await expect(page).toHaveURL(/\/profile$/);
  return token;
}
async function book(page: Page, listing: string, check_in: string, nights = 5) {
  const end = new Date(`${check_in}T12:00:00Z`);
  end.setUTCDate(end.getUTCDate() + nights);
  const query = new URLSearchParams({
    check_in,
    check_out: iso(end),
    guests: "1",
  });
  await page.goto(`/checkout/${listing}?${query}`);
  await expect(page.getByRole("button", { name: /^Pay €/ })).toBeVisible();
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/reservations") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Pay €/ }).click();
  const result = await response;
  expect(result.status()).toBe(201);
  const r = (await result.json()).reservation as Reservation;
  await expect(page).toHaveURL(new RegExp(`/trips/${r.id}$`));
  return r;
}
async function findRequest(page: Page, code: string) {
  await page.goto("/host/today");
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
  throw new Error("Review request missing");
}
async function guestCancel(
  page: Page,
  r: Reservation,
  percent: number,
  shot?: string,
) {
  await page.goto(`/trips/${r.id}`);
  await page.getByRole("link", { name: "Review cancellation" }).click();
  await expect(
    page.getByRole("heading", {
      name: `${percent}% refund on nights and guest service fee`,
    }),
  ).toBeVisible();
  if (shot) await capture(page, shot);
  const response = page.waitForResponse(
    (value) =>
      value.url().endsWith(`/reservations/${r.id}/cancel`) &&
      value.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Cancel reservation", exact: true })
    .click();
  const result = await response;
  expect(result.status()).toBe(200);
  const cancelled = (await result.json()).reservation as Reservation;
  await expect(
    page.getByRole("heading", { name: "Your reservation is cancelled" }),
  ).toBeVisible();
  return cancelled;
}
async function advanceTo(admin: Page, target: Date) {
  const response = await admin.request.get("/api/v1/business-time");
  const current = Date.parse((await response.json()).business_now);
  const seconds = Math.ceil((target.getTime() - current) / 1000);
  if (seconds <= 0)
    throw new Error("Advance target must be forward of current business time");
  await admin.goto("/admin");
  await expect(
    admin.getByRole("button", { name: "Review clock advance" }),
  ).toBeVisible();
  await admin.getByLabel("Advance by seconds").fill(String(seconds));
  await admin.getByRole("button", { name: "Review clock advance" }).click();
  await expect(
    admin.getByRole("heading", { name: "Confirm global clock advance" }),
  ).toBeVisible();
  const result = admin.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/demo/advance") &&
      r.request().method() === "POST",
  );
  await admin.getByRole("button", { name: "Confirm global advance" }).click();
  const value = await result;
  expect(value.status()).toBe(200);
  await expect(
    admin.getByRole("heading", { name: "Sweep results" }),
  ).toBeVisible();
  return value.json();
}
test("isolated demo cancellation refunds, host cancellation, expiry, lifecycle, payouts and event history", async ({
  page,
  browser,
}) => {
  test.setTimeout(240000);
  if (!origin || new URL(origin).port !== "5183")
    throw new Error(
      "This clock-advancing suite requires the separate review stack SMOKE_BASE_URL=http://localhost:5183; shared dev clock is forbidden.",
    );
  const guestToken = await signup(page);
  const hostContext = await browser.newContext();
  const host = await hostContext.newPage();
  const hostToken = await login(host, "HOST");
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const adminToken = await login(admin, "ADMIN");
  const clockResponse = await admin.request.get("/api/v1/admin/demo/clock", {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  expect(clockResponse.status()).toBe(200);
  const baseline = await clockResponse.json();
  expect(baseline.demo_mode).toBe(true);
  const listingResponse = await page.request.get(
    "/api/v1/listings?destination=Lisbon&limit=100",
  );
  const listings = (await listingResponse.json()).items as {
    id: string;
    booking_mode: string;
    demo_label: string | null;
  }[];
  const instant = listings.find(
    (r) => r.demo_label && r.booking_mode === "instant",
  )!;
  const request = listings.find(
    (r) => r.demo_label && r.booking_mode === "request",
  )!;
  expect(instant).toBeTruthy();
  expect(request).toBeTruthy();
  const now = new Date(baseline.business_now);
  const day = (n: number) => iso(new Date(now.getTime() + n * 86400000));
  // Distinct new review records; repeat runs choose dates after the persisted clock.
  const accepted = await book(page, request.id, day(10));
  const card = await findRequest(host, accepted.code);
  await card.getByRole("button", { name: "Accept request" }).click();
  await expect(
    host.locator(".request-card").filter({ hasText: accepted.code }),
  ).toHaveCount(0);
  const full = await guestCancel(page, accepted, 100);
  expect(full.refund?.amount_minor).toBe(full.payment.amount_minor);
  const hostCancelled = await book(page, instant.id, day(12));
  await host.goto(`/trips/${hostCancelled.id}`);
  await host.getByRole("button", { name: "Cancel as host" }).click();
  await host
    .getByLabel("Cancellation reason")
    .fill("Review maintenance requirement");
  const cancelResponse = host.waitForResponse((r) =>
    r.url().endsWith(`/host/reservations/${hostCancelled.id}/cancel`),
  );
  await host.getByRole("button", { name: "Confirm host cancellation" }).click();
  const hostResult = (await (await cancelResponse).json())
    .reservation as Reservation;
  expect(hostResult.state).toBe("cancelled_by_host");
  expect(hostResult.refund?.amount_minor).toBe(hostResult.payment.amount_minor);
  const pending = await book(page, request.id, day(20));
  const half = await book(page, instant.id, day(25));
  const zero = await book(page, instant.id, day(35));
  const short = await book(page, instant.id, day(45), 1);
  const beforeHalf = new Date(
    Date.parse(half.scheduled_check_in) - 48 * 3600000,
  );
  const firstSweep = await advanceTo(admin, beforeHalf);
  expect(firstSweep.sweep.expired).toBeGreaterThanOrEqual(1);
  const partial = await guestCancel(page, half, 50, "cancellation");
  expect(partial.refund?.amount_minor).toBe(40225);
  expect(partial.host_entitlement_minor).toBe(31040);
  expect(partial.effective_host_fee_minor).toBe(960);
  const beforeZero = new Date(
    Date.parse(zero.scheduled_check_in) - 12 * 3600000,
  );
  await advanceTo(admin, beforeZero);
  const cleaning = await guestCancel(page, zero, 0);
  expect(cleaning.refund?.amount_minor).toBe(3500);
  expect(cleaning.host_entitlement_minor).toBe(62080);
  await page.goto(`/trips/${pending.id}`);
  await expect(page.getByText("Expired · fully refunded")).toBeVisible();
  // One-night completion and payout can both be crossed by one large jump.
  const finished = await advanceTo(
    admin,
    new Date(Date.parse(short.scheduled_check_in) + 26 * 3600000),
  );
  expect(finished.sweep.completed).toBeGreaterThanOrEqual(1);
  expect(finished.sweep.paid).toBeGreaterThanOrEqual(1);
  await page.goto(`/trips/${short.id}`);
  await expect(
    page.getByRole("heading", { name: "Your stay is complete" }),
  ).toBeVisible();
  const detailResponse = await page.request.get(
    `/api/v1/reservations/${short.id}`,
    { headers: { Authorization: `Bearer ${guestToken}` } },
  );
  const completed = (await detailResponse.json()).reservation as Reservation;
  expect(completed.state).toBe("completed");
  expect(completed.payout?.status).toBe("paid");
  await host.goto("/host/today");
  await expect(
    host.getByRole("navigation", { name: "Reservation categories" }),
  ).toBeVisible();
  await host.getByRole("button", { name: /Checking out/ }).click();
  await expect(host.getByText(short.code, { exact: true })).toBeVisible();
  await capture(host, "today");
  await host.goto("/host/earnings");
  await expect(
    host.getByRole("table", { name: "Host earnings by reservation" }),
  ).toBeVisible();
  await expect(
    host.getByText("Retained cancellation earnings").first(),
  ).toBeVisible();
  await capture(host, "earnings");
  const earningsResponse = await host.request.get("/api/v1/host/earnings", {
    headers: { Authorization: `Bearer ${hostToken}` },
  });
  const earnings = await earningsResponse.json();
  expect(earnings.totals.paid_minor).toBeGreaterThanOrEqual(
    31040 + 62080 + completed.host_entitlement_minor,
  );
  await admin.goto("/admin");
  await expect(
    admin.getByRole("table", { name: "Recorded events" }),
  ).toBeVisible();
  await capture(admin, "admin");
  await admin.getByLabel("Target UUID").fill(short.id);
  await admin.getByRole("button", { name: "Filter events" }).click();
  await expect(
    admin.getByRole("cell", { name: /reservation.completed/ }),
  ).toBeVisible();
  // Advisory dates come from server business time, even when device time is years behind.
  await page.clock.setFixedTime(new Date("2000-01-01T00:00:00Z"));
  await page.goto(`/stays/${instant.id}`);
  const serverTime = (
    await (await page.request.get("/api/v1/business-time")).json()
  ).business_now as string;
  const min = await page
    .getByLabel("Check in", { exact: true })
    .getAttribute("min");
  expect(min).toBeTruthy();
  expect(min! >= serverTime.slice(0, 10)).toBe(true);
  const finalClock = await admin.request.get("/api/v1/admin/demo/clock", {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  await mkdir("evidence", { recursive: true });
  await writeFile(
    "evidence/m5-browser-records.json",
    JSON.stringify(
      {
        baseline_clock: baseline,
        final_clock: await finalClock.json(),
        accepted_cancelled: {
          id: full.id,
          code: full.code,
          refund_minor: full.refund?.amount_minor,
        },
        host_cancelled: {
          id: hostResult.id,
          code: hostResult.code,
          refund_minor: hostResult.refund?.amount_minor,
        },
        expired: { id: pending.id, code: pending.code },
        half_refund: {
          id: partial.id,
          code: partial.code,
          refund_minor: partial.refund?.amount_minor,
          host_minor: partial.host_entitlement_minor,
          platform_minor: partial.platform_entitlement_minor,
        },
        zero_refund: {
          id: cleaning.id,
          code: cleaning.code,
          refund_minor: cleaning.refund?.amount_minor,
          host_minor: cleaning.host_entitlement_minor,
          platform_minor: cleaning.platform_entitlement_minor,
        },
        completed_paid: {
          id: completed.id,
          code: completed.code,
          payout: completed.payout,
        },
        earnings_totals: earnings.totals,
      },
      null,
      2,
    ),
  );
  await hostContext.close();
  await adminContext.close();
});
