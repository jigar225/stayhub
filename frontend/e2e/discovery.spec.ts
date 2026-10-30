import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
const listingId = "975a5b9c-b000-5f01-b9aa-2a8f9d369ec4";
function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}
async function capture(page: Page, name: string) {
  await mkdir("evidence", { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    if (name === "calendar" && width === 390)
      await expect(page.locator("aside.host-sidebar")).toHaveCSS(
        "transform",
        "matrix(1, 0, 0, 1, -240, 0)",
      );
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect
      .poll(() =>
        page
          .locator("main img")
          .evaluateAll((images) =>
            images.every(
              (image) =>
                (image as HTMLImageElement).complete &&
                (image as HTMLImageElement).naturalWidth > 0,
            ),
          ),
      )
      .toBe(true);
    await page.screenshot({
      path: `evidence/m3-${name}-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
async function seedCredentials() {
  const env = await readFile(new URL("../../.env", import.meta.url), "utf8");
  const values = Object.fromEntries(
    env
      .split("\n")
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const index = line.indexOf("=");
        return [
          line.slice(0, index),
          line.slice(index + 1).replace(/^['"]|['"]$/g, ""),
        ];
      }),
  );
  const email = process.env.SEED_HOST_EMAIL ?? values.SEED_HOST_EMAIL;
  const password = process.env.SEED_HOST_PASSWORD ?? values.SEED_HOST_PASSWORD;
  if (!email || !password)
    throw new Error(
      "Private seed-host credentials are required for the discovery browser check.",
    );
  return { email, password };
}
test("host block excludes a stay, unblock restores it, public quote matches €769.50", async ({
  page,
  browser,
}) => {
  test.setTimeout(120000);
  const { email, password } = await seedCredentials();
  const checkIn = isoDate(new Date(Date.now() + 45 * 86400000));
  const checkOut = isoDate(new Date(Date.now() + 50 * 86400000));
  const calendarPath = `/host/calendar?listing=${listingId}&month=${checkIn.slice(0, 7)}`;
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await page.goto(calendarPath);
  await expect(page.getByRole("table", { name: /availability/ })).toBeVisible();
  await page.getByLabel("Block from", { exact: true }).fill(checkIn);
  await page.getByLabel("Until (exclusive)", { exact: true }).fill(checkOut);
  await page.getByRole("button", { name: "Block dates", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Dates blocked:");
  await expect(
    page.getByRole("button", { name: `Unblock ${checkIn} to ${checkOut}` }),
  ).toBeVisible();
  await capture(page, "calendar");
  const guestContext = await browser.newContext();
  const guest = await guestContext.newPage();
  const searchPath = `/stays?${new URLSearchParams({ destination: "Lisbon", check_in: checkIn, check_out: checkOut, guests: "2" })}`;
  await guest.goto(searchPath);
  await expect(
    guest.getByRole("heading", { name: /No stays match your plans|\d+ stay/ }),
  ).toBeVisible();
  expect(await guest.locator(`a[href^="/stays/${listingId}"]`).count()).toBe(0);
  await page
    .getByRole("button", { name: `Unblock ${checkIn} to ${checkOut}` })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Dates are available again.",
  );
  await guest.reload();
  const stayLink = guest.locator(`a[href^="/stays/${listingId}"]`).first();
  await expect(stayLink).toBeVisible();
  await expect(guest.getByText("€769.50").first()).toBeVisible();
  await expect(guest.getByLabel("Where")).toHaveValue("Lisbon");
  await capture(guest, "results");
  await stayLink.click();
  await expect(
    guest.getByRole("link", { name: "Reserve", exact: true }),
  ).toBeVisible();
  await expect(guest.locator(".quote-total")).toContainText("€769.50");
  await expect(guest.locator(".quote-lines")).toContainText("€675.00");
  await expect(guest.locator(".quote-lines")).toContainText("€94.50");
  await expect(
    guest.getByRole("heading", { name: "Cancellation policy · Moderate" }),
  ).toBeVisible();
  await expect(
    guest.getByRole("link", { name: "Reserve", exact: true }),
  ).toHaveAttribute(
    "href",
    new RegExp(`/checkout/${listingId}.*check_in=${checkIn}`),
  );
  await capture(guest, "detail");
  await guest.reload();
  await expect(guest.locator(".quote-total")).toContainText("€769.50");
  await expect(guest.getByLabel("Check in")).toHaveValue(checkIn);
  await guest.getByRole("link", { name: "← Back to stays" }).click();
  await expect(guest).toHaveURL(new RegExp(`check_in=${checkIn}`));
  await expect(guest.getByLabel("Check out")).toHaveValue(checkOut);
  await guestContext.close();
});

for (const scenario of [
  { mode: "instant", now: "2027-01-15T09:29:59Z", min: "2027-01-15" },
  { mode: "instant", now: "2027-01-15T09:30:00Z", min: "2027-01-16" },
  { mode: "instant", now: "2027-01-15T10:00:00Z", min: "2027-01-16" },
  { mode: "request", now: "2027-01-14T09:30:00Z", min: "2027-01-15" },
  { mode: "request", now: "2027-01-14T09:30:01Z", min: "2027-01-16" },
]) {
  test(`listing-local date picker ${scenario.mode} at ${scenario.now}`, async ({
    page,
  }) => {
    await page.clock.setFixedTime(new Date(scenario.now));
    await page.addInitScript(() =>
      Object.defineProperty(performance, "now", { value: () => 1000 }),
    );
    await page.route("**/api/v1/business-time", (route) =>
      route.fulfill({
        json: { business_now: scenario.now, real_now: scenario.now },
      }),
    );
    await page.route(`**/api/v1/listings/${listingId}`, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.listing.timezone = "Asia/Kolkata";
      body.listing.booking_mode = scenario.mode;
      body.listing.check_in_time = "15:00";
      await route.fulfill({ response, json: body });
    });
    await page.goto(`/stays/${listingId}`);
    const arrival = page.getByLabel("Check in", { exact: true });
    const departure = page.getByLabel("Check out", { exact: true });
    await expect(arrival).toHaveAttribute("min", scenario.min);
    await arrival.fill("2027-01-17");
    await departure.fill("2027-01-18");
    await expect(departure).toHaveAttribute("min", "2027-01-18");
    await arrival.fill("2027-01-18");
    await expect(departure).toHaveValue("");
    await expect(page.getByText(/Check-in changed/)).toBeVisible();
    await arrival.fill("2000-01-01");
    await departure.fill("2000-01-02");
    await page.getByRole("button", { name: "Check price" }).click();
    await expect(page.getByText(/Choose a later check-in date/)).toBeVisible();
  });
}

test("edited past URL dates show real API validation and permit correction", async ({
  page,
}) => {
  await page.goto(
    `/stays/${listingId}?check_in=2000-01-01&check_out=2000-01-02&guests=1`,
  );
  await expect(page.getByLabel("Check in", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByText(/Choose a later check-in date/)).toBeVisible();
  const response = await page.request.post("/api/v1/booking-quotes", {
    data: {
      listing_id: listingId,
      check_in: "2000-01-01",
      check_out: "2000-01-02",
      guests: 1,
    },
  });
  expect(response.status()).toBe(422);
  expect((await response.json()).error.field_errors.check_in).toBeTruthy();
  const arrival = isoDate(new Date(Date.now() + 60 * 86400000));
  const departure = isoDate(new Date(Date.now() + 61 * 86400000));
  await page.getByLabel("Check in", { exact: true }).fill(arrival);
  await page.getByLabel("Check out", { exact: true }).fill(departure);
  await page.getByRole("button", { name: "Check price" }).click();
  await expect(page.locator(".quote-total")).toBeVisible();
});

test("cross-timezone search picker uses a conservative date and backend errors remain actionable", async ({
  browser,
}) => {
  const context = await browser.newContext({
    timezoneId: "Pacific/Kiritimati",
  });
  const page = await context.newPage();
  await page.clock.setFixedTime(new Date("2027-01-15T01:00:00Z"));
  await page.route("**/api/v1/business-time", (route) =>
    route.fulfill({
      json: {
        business_now: "2027-01-15T01:00:00Z",
        real_now: "2027-01-15T01:00:00Z",
      },
    }),
  );
  await page.goto("/stays");
  await expect(page.getByLabel("Check in", { exact: true })).toHaveAttribute(
    "min",
    "2027-01-14",
  );
  await page.goto(
    "/stays?destination=Lisbon&check_in=2000-01-01&check_out=2000-01-02&guests=1",
  );
  await expect(page.getByRole("alert")).toContainText(/past/);
  await expect(page.getByLabel("Check in", { exact: true })).toBeEnabled();
  await context.close();
});

test("quote field feedback survives a server rejection and guests can correct dates", async ({
  page,
}) => {
  const arrival = isoDate(new Date(Date.now() + 65 * 86400000));
  const departure = isoDate(new Date(Date.now() + 66 * 86400000));
  await page.route("**/api/v1/booking-quotes", async (route) => {
    await route.fulfill({
      status: 422,
      json: {
        error: {
          code: "validation_error",
          message: "Check-in is unavailable.",
          field_errors: {
            check_in: "Choose a later date before scheduled check-in.",
          },
          request_id: "browser-fixture",
        },
      },
    });
  });
  await page.goto(
    `/stays/${listingId}?check_in=${arrival}&check_out=${departure}&guests=1`,
  );
  await expect(page.getByRole("alert")).toContainText(
    "Choose a later date before scheduled check-in.",
  );
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Choose a later date before scheduled check-in.",
  );
  await page.unroute("**/api/v1/booking-quotes");
  await page.getByLabel("Check in", { exact: true }).fill(departure);
  await expect(page.getByLabel("Check out", { exact: true })).toHaveValue("");
  await page
    .getByLabel("Check out", { exact: true })
    .fill(isoDate(new Date(Date.now() + 67 * 86400000)));
  await page.getByRole("button", { name: "Check price" }).click();
  await expect(page.locator(".quote-total")).toBeVisible();
});
