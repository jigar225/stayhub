import { test, expect } from "@playwright/test";
const listingId = "975a5b9c-b000-5f01-b9aa-2a8f9d369ec4";
const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const format = (value: string) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
test("all photos and real unavailable nights remain integrated with quote and Reserve", async ({
  page,
}) => {
  if (!process.env.SEED_HOST_EMAIL || !process.env.SEED_HOST_PASSWORD)
    throw new Error("Isolated seed host credentials required");
  const login = await page.request.post("/api/v1/auth/login", {
    headers: { Origin: origin },
    data: {
      email: process.env.SEED_HOST_EMAIL,
      password: process.env.SEED_HOST_PASSWORD,
    },
  });
  expect(login.status()).toBe(200);
  const token = (await login.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}`, Origin: origin };
  const clock = await (await page.request.get("/api/v1/business-time")).json();
  const future = new Date(clock.business_now);
  future.setUTCDate(future.getUTCDate() + 80);
  let blockId = "",
    start = "",
    end = "",
    arrival = "";
  for (let month = 0; month < 8; month++) {
    const day = new Date(
      Date.UTC(future.getUTCFullYear(), future.getUTCMonth() + month, 15),
    )
      .toISOString()
      .slice(0, 10);
    const checkout = day.slice(0, 8) + "17";
    const response = await page.request.post(
      `/api/v1/host/listings/${listingId}/blocks`,
      { headers, data: { check_in: day, check_out: checkout } },
    );
    if (response.status() === 409) continue;
    expect(response.status()).toBe(201);
    blockId = (await response.json()).block.id;
    start = day;
    end = checkout;
    arrival = day.slice(0, 8) + "14";
    break;
  }
  expect(blockId).toBeTruthy();
  try {
    await page.goto(
      `/stays/${listingId}?check_in=${arrival}&check_out=${start}&guests=1`,
    );
    const show = page.getByRole("button", { name: /Show all \d+ photos/ });
    await show.click();
    const viewer = page.getByRole("dialog", { name: /Photos$/ });
    await expect(viewer).toBeVisible();
    await expect(viewer.getByRole("status")).toHaveText("Photo 1 of 5");
    await viewer.press("End");
    await expect(viewer.getByRole("status")).toHaveText("Photo 5 of 5");
    await viewer.press("ArrowRight");
    await expect(viewer.getByRole("status")).toHaveText("Photo 1 of 5");
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await viewer.evaluate((element) => element.scrollWidth <= innerWidth),
    ).toBe(true);
    await viewer.press("Escape");
    await expect(viewer).toHaveCount(0);
    await expect(show).toBeFocused();
    const availability = page.locator(".stay-availability");
    await expect(
      availability.getByRole("button", {
        name: `${format(start)}, Unavailable night`,
      }),
    ).toBeVisible();
    await availability.getByRole("button", { name: "Clear selection" }).click();
    await expect(
      availability.getByRole("button", {
        name: `${format(start)}, Unavailable night`,
      }),
    ).toBeDisabled();
    await availability
      .getByRole("button", { name: `${format(arrival)}, Available night` })
      .click();
    await availability
      .getByRole("button", { name: `${format(start)}, Unavailable night` })
      .click();
    await availability
      .getByRole("button", { name: "Check these dates" })
      .click();
    await expect(
      page.getByRole("link", { name: "Reserve", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".quote-lines")).toBeVisible();
    // Occupancy remains authoritative even when dates are supplied directly.
    const unavailableQuote = await page.request.post("/api/v1/booking-quotes", {
      data: {
        listing_id: listingId,
        check_in: start,
        check_out: end,
        guests: 1,
      },
    });
    expect(unavailableQuote.status()).toBe(409);
  } finally {
    const removed = await page.request.delete(
      `/api/v1/host/listings/${listingId}/blocks/${blockId}`,
      { headers },
    );
    expect(removed.status()).toBe(204);
  }
});
