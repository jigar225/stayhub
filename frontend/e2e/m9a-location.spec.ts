import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const id = "975a5b9c-b000-5f01-b9aa-2a8f9d369ec4";
const dir = process.env.SMOKE_EVIDENCE_DIR ?? "evidence/m9a";
async function capture(page: Page, state: string, width: number) {
  await page.evaluate(() => document.fonts.ready);
  if (["selected-pin", "saved-reloaded", "public-map"].includes(state)) {
    await expect(page.locator(".location-map-notice")).toHaveCount(0);
    await expect(
      page.getByText("Map unavailable", { exact: true }),
    ).toHaveCount(0);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `${dir}/m9a-${state}-${width}.png`,
    fullPage: true,
  });
}
for (const width of [1440, 390]) {
  test(`location select save reload and public privacy ${width}`, async ({
    page,
    browser,
  }) => {
    test.setTimeout(120000);
    await mkdir(dir, { recursive: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto("/login");
    await page.getByLabel("Email address").fill(process.env.SEED_HOST_EMAIL!);
    await page
      .getByLabel("Password", { exact: true })
      .fill(process.env.SEED_HOST_PASSWORD!);
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/profile$/);
    await page.goto(`/host/listings/${id}/edit`);
    const address = page.getByRole("combobox", { name: "Street address" });
    await expect(address).toBeVisible();
    let searches = 0;
    // Fake provider: UI evidence only, never live Geoapify verification.
    await page.route("**/api/v1/host/location/autocomplete", (route) => {
      searches++;
      return route.fulfill({
        json: {
          items: [
            {
              display_address: "M9A test address, Lisbon, Portugal",
              latitude: 38.713456,
              longitude: -9.134567,
            },
          ],
          attribution: "Powered by Geoapify",
        },
      });
    });
    await address.fill("M9A test address, apt 4");
    await expect(page.locator('[role="option"]')).toBeVisible();
    await capture(page, "mock-suggestions", width);
    await address.press("ArrowDown");
    await expect(address).toHaveAttribute("aria-activedescendant", /option-0$/);
    await address.press("Escape");
    await expect(page.locator('[role="option"]')).toHaveCount(0);
    await address.press("ArrowDown");
    await address.press("Enter");
    await expect(address).toHaveValue(/apt 4$/);
    if (width === 390) {
      await address.fill("M9A pointer test, apt 4");
      await page.locator('[role="option"]').click();
    }
    await expect(page.getByText(/Pin selected/)).toBeVisible();
    await page.getByLabel("Latitude", { exact: true }).fill("38.713789");
    await page.getByLabel("Longitude", { exact: true }).fill("-9.134987");
    await expect(page.getByText(/No confirmed pin/)).toBeVisible();
    await page
      .getByRole("button", { name: "Confirm pin", exact: true })
      .click();
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    await expect(page.getByText("OpenFreeMap", { exact: true })).toBeVisible({
      timeout: 25000,
    });
    await capture(page, "selected-pin", width);
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(
      page.getByText("All changes saved", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Latitude", { exact: true })).toHaveValue(
      "38.713789",
    );
    await expect(page.getByLabel("Longitude", { exact: true })).toHaveValue(
      "-9.134987",
    );
    await expect(page.getByText(/Pin selected/)).toBeVisible();
    await capture(page, "saved-reloaded", width);
    await address.fill("Edited address needs reconfirmation");
    await expect(page.getByText(/No confirmed pin/)).toBeVisible();
    await expect(page.getByLabel("Latitude", { exact: true })).toHaveValue("");
    expect(searches).toBeGreaterThan(0);
    const publicContext = await browser.newContext({
      viewport: { width, height: width === 390 ? 844 : 900 },
    });
    const guest = await publicContext.newPage();
    const response = await guest.request.get(`/api/v1/listings/${id}/location`);
    expect(await response.json()).toEqual({
      location: {
        latitude: 38.71,
        longitude: -9.13,
        grid_degrees: 0.01,
        radius_meters: 800,
        max_zoom: 12,
      },
    });
    const publicDetail = await guest.request.get(`/api/v1/listings/${id}`);
    expect(JSON.stringify(await publicDetail.json())).not.toMatch(
      /latitude|longitude|38\.713789|-9\.134987/,
    );
    await guest.goto(
      `/stays/${id}?check_in=2027-04-01&check_out=2027-04-03&guests=1`,
    );
    await expect(
      guest.getByRole("link", { name: "Reserve", exact: true }),
    ).toBeVisible();
    await expect(
      guest.getByText("Approximate location", { exact: true }),
    ).toBeVisible();
    await expect(guest.getByText("OpenFreeMap", { exact: true })).toBeVisible({
      timeout: 25000,
    });
    await capture(guest, "public-map", width);
    expect(await guest.locator("body").innerHTML()).not.toMatch(
      /38\.713789|-9\.134987/,
    );
    await guest.route("https://tiles.openfreemap.org/**", (route) =>
      route.abort(),
    );
    await guest.reload();
    await expect(
      guest.getByText("Map unavailable", { exact: true }),
    ).toBeVisible({ timeout: 25000 });
    await expect(
      guest.getByRole("link", { name: "Reserve", exact: true }),
    ).toBeVisible();
    await capture(guest, "map-failure", width);
    await guest.unroute("https://tiles.openfreemap.org/**");
    await guest.getByRole("button", { name: "Retry map", exact: true }).click();
    await expect(
      guest.getByText("Map unavailable", { exact: true }),
    ).toHaveCount(0);
    await publicContext.close();
    page.on("dialog", (dialog) => dialog.accept());
  });
}
