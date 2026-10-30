import { test, expect, type Page } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import type { Reservation } from "../src/booking/api";
import type { PublicSummary, PublicPhoto } from "../src/discovery/api";
const base = process.env.SMOKE_BASE_URL;
const out = "../evidence/m61";
function coldOnly() {
  if (base !== "http://localhost:5193")
    throw new Error(
      "Cold-volume verification requires localhost:5193; existing clocks are forbidden.",
    );
}
async function login(page: Page, role: "GUEST" | "HOST" | "ADMIN") {
  const email = process.env[`SEED_${role}_EMAIL`];
  const password = process.env[`SEED_${role}_PASSWORD`];
  if (!email || !password)
    throw new Error("Private cold-stack seed credentials required");
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const result = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  const response = await result;
  expect(response.status()).toBe(200);
  const auth = await response.json();
  await expect(page).toHaveURL(/\/profile$/);
  const me = await page.request.get("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  });
  expect((await me.json()).user.roles).toContain(role.toLowerCase());
  return auth.access_token as string;
}
async function photos(page: Page) {
  const response = await page.request.get("/api/v1/listings?limit=100");
  expect(response.status()).toBe(200);
  const listings = (await response.json()).items as PublicSummary[];
  expect(listings).toHaveLength(6);
  const ids: string[] = [];
  for (const listing of listings) {
    const result = await page.request.get(
      `/api/v1/listings/${listing.id}/photos`,
    );
    expect(result.status()).toBe(200);
    const items = (await result.json()).items as PublicPhoto[];
    expect(items).toHaveLength(5);
    for (const photo of items) {
      expect(new URL(photo.url).port).toBe("9020");
      const image = await page.request.get(photo.url);
      expect(image.status()).toBe(200);
      expect(image.headers()["content-type"]).toMatch(/^image\//);
      expect((await image.body()).length).toBeGreaterThan(100);
      ids.push(photo.id);
    }
  }
  return { listings, photoIds: ids.sort() };
}
async function book(page: Page, id: string, checkIn: string, nights: number) {
  const end = new Date(`${checkIn}T12:00:00Z`);
  end.setUTCDate(end.getUTCDate() + nights);
  await page.goto(
    `/checkout/${id}?${new URLSearchParams({ check_in: checkIn, check_out: end.toISOString().slice(0, 10), guests: "1" })}`,
  );
  const pay = page.getByRole("button", { name: /^Pay €/ });
  await expect(pay).toBeVisible();
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/reservations") && r.request().method() === "POST",
  );
  await pay.click();
  const result = await response;
  expect(result.status()).toBe(201);
  const reservation = (await result.json()).reservation as Reservation;
  await expect(page).toHaveURL(new RegExp(`/trips/${reservation.id}$`));
  return reservation;
}
async function readReservation(page: Page, token: string, id: string) {
  const response = await page.request.get(`/api/v1/reservations/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).reservation as Reservation;
}
async function capture(page: Page, name: string) {
  await mkdir(`${out}/screenshots`, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${out}/screenshots/${name}-${width}.png`,
      fullPage: true,
    });
  }
}
test("fresh-volume seeded logins/photos, accepted booking refund and one-night payout", async ({
  page,
  browser,
}) => {
  coldOnly();
  test.setTimeout(180000);
  const guest = await login(page, "GUEST");
  const hostContext = await browser.newContext();
  const host = await hostContext.newPage();
  const hostToken = await login(host, "HOST");
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const adminToken = await login(admin, "ADMIN");
  const initial = await photos(page);
  const request = initial.listings.find(
    (r) => r.destination === "Lisbon" && r.booking_mode === "request",
  )!;
  const instant = initial.listings.find(
    (r) => r.destination === "Lisbon" && r.booking_mode === "instant",
  )!;
  expect(request).toBeTruthy();
  expect(instant).toBeTruthy();
  const clock = await (await page.request.get("/api/v1/business-time")).json();
  const day = (n: number) =>
    new Date(Date.parse(clock.business_now) + n * 86400000)
      .toISOString()
      .slice(0, 10);
  await page.goto(`/stays/${instant.id}`);
  await expect(page.locator(".public-gallery img").first()).toBeVisible();
  await capture(page, "seeded-detail");
  const pending = await book(page, request.id, day(10), 5);
  expect(pending.state).toBe("pending");
  await host.goto("/host/today");
  const card = host.locator(".request-card").filter({ hasText: pending.code });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Accept request" }).click();
  await expect(card).toHaveCount(0);
  await page.goto(`/trips/${pending.id}/cancel`);
  await expect(
    page.getByRole("heading", {
      name: "100% refund on nights and guest service fee",
    }),
  ).toBeVisible();
  const cancelledResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/reservations/${pending.id}/cancel`) &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Cancel reservation", exact: true })
    .click();
  expect((await cancelledResponse).status()).toBe(200);
  const cancelled = await readReservation(page, guest, pending.id);
  expect(cancelled.state).toBe("cancelled_by_guest");
  expect(cancelled.refund?.amount_minor).toBe(cancelled.payment.amount_minor);
  expect(cancelled.host_entitlement_minor).toBe(0);
  await capture(page, "refunded");
  const short = await book(page, instant.id, day(15), 1);
  expect(short.state).toBe("confirmed");
  const seconds = Math.ceil(
    (Date.parse(short.scheduled_check_in) +
      26 * 3600000 -
      Date.parse(clock.business_now)) /
      1000,
  );
  await admin.goto("/admin");
  await admin.getByLabel("Advance by seconds").fill(String(seconds));
  await admin.getByRole("button", { name: "Review clock advance" }).click();
  const advanced = admin.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/demo/advance") &&
      r.request().method() === "POST",
  );
  await admin.getByRole("button", { name: "Confirm global advance" }).click();
  expect((await advanced).status()).toBe(200);
  await page.goto(`/trips/${short.id}`);
  await expect(
    page.getByRole("heading", { name: "Your stay is complete" }),
  ).toBeVisible();
  const completed = await readReservation(page, guest, short.id);
  expect(completed.payout?.status).toBe("paid");
  expect(completed.payout?.net_minor).toBe(15811);
  for (const r of [cancelled, completed])
    expect(r.payment.amount_minor - (r.refund?.amount_minor ?? 0)).toBe(
      r.host_entitlement_minor + r.platform_entitlement_minor,
    );
  await host.goto("/host/earnings");
  await expect(
    host.getByRole("table", { name: "Host earnings by reservation" }),
  ).toBeVisible();
  const earnings = await (
    await host.request.get("/api/v1/host/earnings", {
      headers: { Authorization: `Bearer ${hostToken}` },
    })
  ).json();
  expect(earnings.totals).toEqual({
    paid_minor: 15811,
    upcoming_minor: 0,
    held_minor: 0,
  });
  await capture(host, "earnings");
  const finalClock = await (
    await admin.request.get("/api/v1/admin/demo/clock", {
      headers: { Authorization: `Bearer ${adminToken}` },
    })
  ).json();
  await writeFile(
    `${out}/journey.json`,
    JSON.stringify(
      {
        seeded_roles: ["guest", "host", "admin"],
        listing_ids: initial.listings.map((r) => r.id).sort(),
        photo_ids: initial.photoIds,
        cancelled,
        completed,
        earnings: earnings.totals,
        clock: finalClock,
      },
      null,
      2,
    ) + "\n",
  );
  await hostContext.close();
  await adminContext.close();
});
test("seed reruns and restart retain six stays, thirty photos and reconciled bookings", async ({
  page,
  browser,
}) => {
  coldOnly();
  test.setTimeout(120000);
  const saved = JSON.parse(await readFile(`${out}/journey.json`, "utf8"));
  const token = await login(page, "GUEST");
  const actual = await photos(page);
  expect(actual.photoIds).toEqual(saved.photo_ids);
  expect(actual.listings.map((r) => r.id).sort()).toEqual(saved.listing_ids);
  for (const r of [saved.cancelled, saved.completed])
    expect(await readReservation(page, token, r.id)).toEqual(r);
  const context = await browser.newContext();
  const host = await context.newPage();
  const hostToken = await login(host, "HOST");
  const earnings = await (
    await host.request.get("/api/v1/host/earnings", {
      headers: { Authorization: `Bearer ${hostToken}` },
    })
  ).json();
  expect(earnings.totals).toEqual(saved.earnings);
  await context.close();
  await writeFile(
    `${out}/post-restart-browser.json`,
    JSON.stringify(
      {
        logins_work: true,
        six_listing_ids_identical: true,
        thirty_photo_ids_identical_and_http200: true,
        reservations_identical: true,
        earnings_identical: true,
      },
      null,
      2,
    ) + "\n",
  );
});
