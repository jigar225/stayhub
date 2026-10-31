import { test, expect, type Page, type Route } from "@playwright/test";
import path from "node:path";

// The suite has two real, read-only server tests. Tests in the transport group
// deliberately intercept discovery responses to reproduce failure and race states.
const listings = [
  {
    title: "M8 courtyard apartment",
    property_type: "apartment",
    nightly_minor: 6010,
    beds: 2,
    bedrooms: 1,
    amenities: ["wifi", "kitchen"],
    booking_mode: "instant",
    categories: ["design"],
  },
  {
    title: "M8 private garden room",
    property_type: "room",
    nightly_minor: 7999,
    beds: 1,
    bedrooms: 1,
    amenities: ["wifi"],
    booking_mode: "request",
    categories: ["cabins"],
  },
  {
    title: "M8 kitchen house",
    property_type: "house",
    nightly_minor: 12800,
    beds: 3,
    bedrooms: 2,
    amenities: ["wifi", "kitchen"],
    booking_mode: "instant",
    categories: ["design"],
  },
  {
    title: "M8 quiet apartment",
    property_type: "apartment",
    nightly_minor: 18000,
    beds: 2,
    bedrooms: 2,
    amenities: ["kitchen"],
    booking_mode: "request",
    categories: ["design"],
  },
].map((listing, index) => ({
  ...listing,
  id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  destination: "Lisbon",
  capacity: 4,
  baths: 1,
  cleaning_minor: 0,
  photos: [
    {
      id: `m8-photo-${index}`,
      url: "/m8-fixture.jpg",
      expires_at: "2030-01-01T00:00:00Z",
      width: 1280,
      height: 850,
    },
  ],
  stay_price: null,
  demo_label: "Isolated browser fixture",
}));

type Listing = (typeof listings)[number];
type Respond = (route: Route, url: URL) => Promise<void> | void;

async function fixtures(page: Page, respond?: Respond) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/csrf"))
      return route.fulfill({ json: { csrf_token: "isolated-m8" } });
    if (url.pathname.endsWith("/auth/refresh"))
      return route.fulfill({
        status: 401,
        json: {
          error: {
            code: "unauthenticated",
            message: "Signed out",
            field_errors: null,
          },
        },
      });
    if (url.pathname.endsWith("/business-time"))
      return route.fulfill({
        json: {
          business_now: "2026-10-30T12:00:00Z",
          real_now: "2026-10-30T12:00:00Z",
        },
      });
    if (url.pathname.endsWith("/listings")) {
      if (respond) return respond(route, url);
      return route.fulfill({
        json: { items: filtered(url.searchParams), next_cursor: null },
      });
    }
    throw new Error(`Unmatched M8 fixture request: ${url.pathname}`);
  });
  await page.route("**/m8-fixture.jpg", (route) =>
    route.fulfill({
      path: path.resolve("../demo/assets/pexels-16978555.jpg"),
      contentType: "image/jpeg",
    }),
  );
}

function filtered(params: URLSearchParams): Listing[] {
  return listings.filter(
    (listing) =>
      (!params.has("category") ||
        listing.categories.includes(params.get("category")!)) &&
      (!params.has("place_group") ||
        (params.get("place_group") === "private"
          ? listing.property_type === "room"
          : listing.property_type !== "room")) &&
      (!params.has("min_price_minor") ||
        listing.nightly_minor >= Number(params.get("min_price_minor"))) &&
      (!params.has("max_price_minor") ||
        listing.nightly_minor <= Number(params.get("max_price_minor"))) &&
      (!params.has("min_bedrooms") ||
        listing.bedrooms >= Number(params.get("min_bedrooms"))) &&
      (!params.has("min_beds") ||
        listing.beds >= Number(params.get("min_beds"))) &&
      params
        .getAll("amenity")
        .every((value) => listing.amenities.includes(value)) &&
      (params.get("instant_book") !== "true" ||
        listing.booking_mode === "instant"),
  );
}

function filtersButton(page: Page) {
  return page.getByRole("button", { name: /^Filters(?:\b| ·)/ });
}
async function openFilters(page: Page) {
  await filtersButton(page).click();
  const dialog = page.getByRole("dialog", { name: "Filters", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

for (const route of ["/", "/stays"]) {
  test(`real server: ${route} applies an inclusive nightly-price predicate without altering source data`, async ({
    page,
  }) => {
    const base = await page.request.get("/api/v1/listings?limit=100");
    expect(base.status()).toBe(200);
    const all = (await base.json()).items as {
      id: string;
      nightly_minor: number;
    }[];
    expect(all.length).toBeGreaterThan(0);
    const ceiling = Math.min(...all.map((item) => item.nightly_minor));
    await page.goto(route);
    await expect(page.locator(".public-stay-card").first()).toBeVisible();
    const dialog = await openFilters(page);
    await dialog
      .getByLabel("Maximum", { exact: true })
      .fill((ceiling / 100).toFixed(2));
    const response = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/listings" &&
        url.searchParams.get("max_price_minor") === String(ceiling)
      );
    });
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    const result = await (await response).json();
    expect(result.items.length).toBeGreaterThan(0);
    expect(
      result.items.every(
        (item: { nightly_minor: number }) => item.nightly_minor <= ceiling,
      ),
    ).toBe(true);
    await expect(page.locator(".public-stay-card")).toHaveCount(
      result.items.length,
    );
    const expected = new Set(
      all
        .filter((item) => item.nightly_minor <= ceiling)
        .map((item) => item.id),
    );
    expect(
      new Set(result.items.map((item: { id: string }) => item.id)),
    ).toEqual(expected);
    await page.reload();
    await expect(page.locator(".public-stay-card")).toHaveCount(
      result.items.length,
    );
    await expect(filtersButton(page)).toContainText("1");
  });
}

test.describe("isolated mocked discovery transport", () => {
  test("drawer drafts apply exactly, cancel/discard, clear preserves the search, and history restores committed filters", async ({
    page,
  }) => {
    await fixtures(page);
    await page.goto(
      "/?destination=Lisbon&check_in=2027-02-01&check_out=2027-02-04&guests=2&category=design",
    );
    await expect(page.locator(".public-stay-card")).toHaveCount(3);
    const initial = page.url();
    let dialog = await openFilters(page);
    await dialog
      .getByRole("radio", { name: "Private room", exact: true })
      .check();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(filtersButton(page)).toBeFocused();
    expect(page.url()).toBe(initial);
    dialog = await openFilters(page);
    await expect(
      dialog.getByRole("radio", { name: "Any type", exact: true }),
    ).toBeChecked();
    await dialog
      .getByRole("radio", { name: "Entire place", exact: true })
      .check();
    await dialog.getByLabel("Minimum", { exact: true }).fill("60.10");
    await dialog.getByLabel("Maximum", { exact: true }).fill("128.00");
    await dialog
      .getByRole("button", { name: "Increase minimum bedrooms", exact: true })
      .click();
    await expect(dialog.getByLabel("Minimum bedrooms value")).toHaveText("1+");
    await dialog
      .getByRole("button", { name: "Increase minimum beds", exact: true })
      .click();
    await dialog
      .getByRole("button", { name: "Increase minimum beds", exact: true })
      .click();
    await expect(dialog.getByLabel("Minimum beds value")).toHaveText("2+");
    await dialog.getByRole("checkbox", { name: "Wifi", exact: true }).check();
    await dialog
      .getByRole("checkbox", { name: "Kitchen", exact: true })
      .check();
    await dialog.getByRole("checkbox", { name: /Instant book/ }).check();
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    await expect(page.locator(".public-stay-card")).toHaveCount(2);
    const applied = new URL(page.url()).searchParams;
    expect(applied.get("min_price_minor")).toBe("6010");
    expect(applied.get("max_price_minor")).toBe("12800");
    expect(applied.getAll("amenity").sort()).toEqual(["kitchen", "wifi"]);
    expect(applied.get("place_group")).toBe("entire");
    expect(applied.get("min_bedrooms")).toBe("1");
    expect(applied.get("min_beds")).toBe("2");
    expect(applied.get("instant_book")).toBe("true");
    await expect(filtersButton(page)).toContainText("7");
    await page.getByRole("button", { name: "Cabins", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "No stays match your plans" }),
    ).toBeVisible();
    expect(new URL(page.url()).searchParams.getAll("amenity").sort()).toEqual([
      "kitchen",
      "wifi",
    ]);
    await page.goBack();
    await expect(page.locator(".public-stay-card")).toHaveCount(2);
    await page.reload();
    await expect(page.locator(".public-stay-card")).toHaveCount(2);
    await page.locator('[name="guests"]').fill("3");
    await page.locator('.stay-search button[type="submit"]').click();
    await expect(page).toHaveURL(/\/stays\?/);
    expect(new URL(page.url()).searchParams.getAll("amenity").sort()).toEqual([
      "kitchen",
      "wifi",
    ]);
    expect(new URL(page.url()).searchParams.get("guests")).toBe("3");
    dialog = await openFilters(page);
    await dialog
      .getByRole("button", { name: "Clear all", exact: true })
      .click();
    expect(new URL(page.url()).searchParams.has("min_price_minor")).toBe(true);
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    const cleared = new URL(page.url()).searchParams;
    expect(cleared.get("destination")).toBe("Lisbon");
    expect(cleared.get("check_in")).toBe("2027-02-01");
    expect(cleared.get("check_out")).toBe("2027-02-04");
    expect(cleared.get("guests")).toBe("3");
    expect(cleared.get("category")).toBe("design");
    for (const key of [
      "place_group",
      "min_bedrooms",
      "min_beds",
      "min_price_minor",
      "max_price_minor",
      "amenity",
      "instant_book",
    ])
      expect(cleared.has(key)).toBe(false);
    await page.goBack();
    await expect(filtersButton(page)).toContainText("7");
  });

  test("price validation prevents lossy cents, inverted ranges and out-of-bounds input", async ({
    page,
  }) => {
    await fixtures(page);
    await page.goto("/stays");
    const original = page.url();
    const dialog = await openFilters(page);
    const min = dialog.getByLabel("Minimum", {
      exact: true,
    });
    const max = dialog.getByLabel("Maximum", {
      exact: true,
    });
    for (const value of ["60.101", "-1", "1e2", "100000.01"]) {
      await min.fill(value);
      await dialog
        .getByRole("button", { name: "Show stays", exact: true })
        .click();
      await expect(dialog).toBeVisible();
      await expect(min).toHaveAttribute("aria-invalid", "true");
      expect(page.url()).toBe(original);
    }
    await min.fill("180");
    await max.fill("60");
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    await expect(dialog).toBeVisible();
    expect(page.url()).toBe(original);
    await min.fill("0.29");
    await max.fill("180");
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    await expect(dialog).not.toBeVisible();
    expect(new URL(page.url()).searchParams.get("min_price_minor")).toBe("29");
  });

  test("keyboard modal traps focus, backdrop discards, and mobile controls do not overflow", async ({
    page,
  }) => {
    await fixtures(page);
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto("/");
      const dialog = await openFilters(page);
      const close = dialog.getByRole("button", {
        name: "Close filters",
        exact: true,
      });
      const apply = dialog.getByRole("button", {
        name: "Show stays",
        exact: true,
      });
      await close.focus();
      await page.keyboard.press("Shift+Tab");
      await expect(apply).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(close).toBeFocused();
      await dialog
        .getByRole("radio", { name: "Private room", exact: true })
        .check();
      if (viewport.width === 1440) {
        await page.mouse.click(4, 4);
      } else {
        await page.keyboard.press("Escape");
      }
      await expect(dialog).not.toBeVisible();
      await expect(filtersButton(page)).toBeFocused();
      await openFilters(page);
      await expect(
        dialog.getByRole("radio", { name: "Any type", exact: true }),
      ).toBeChecked();
      expect(
        await dialog.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.keyboard.press("Escape");
      const guests = page.locator('[name="guests"]');
      await guests.focus();
      await page.keyboard.press("ArrowUp");
      await expect(guests).toHaveValue("2");
      await page.keyboard.press("Tab");
      await expect(
        page.locator('.stay-search button[type="submit"]'),
      ).toBeFocused();
    }
  });

  test("retry and pagination retain repeated amenities; changed filters reset cursor", async ({
    page,
  }) => {
    let failing = true;
    let failPage = true;
    const requests: URL[] = [];
    await fixtures(page, (route, url) => {
      requests.push(url);
      if (failing)
        return route.fulfill({
          status: 503,
          json: {
            error: {
              code: "unavailable",
              message: "M8 isolated transport failure",
              field_errors: null,
            },
          },
        });
      if (url.searchParams.has("cursor") && failPage) {
        failPage = false;
        return route.fulfill({
          status: 503,
          json: {
            error: {
              code: "unavailable",
              message: "M8 isolated page failure",
              field_errors: null,
            },
          },
        });
      }
      return route.fulfill({
        json: {
          items: url.searchParams.has("cursor") ? [listings[2]] : [listings[0]],
          next_cursor: url.searchParams.has("cursor") ? null : "m8-next",
        },
      });
    });
    await page.goto(
      "/stays?amenity=wifi&amenity=kitchen&min_price_minor=6000&guests=2",
    );
    await expect(page.getByRole("alert")).toContainText(
      "M8 isolated transport failure",
    );
    failing = false;
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.locator(".public-stay-card")).toHaveCount(1);
    await page
      .getByRole("button", { name: "Load more stays", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "M8 isolated page failure",
    );
    await expect(page.locator(".public-stay-card")).toHaveCount(1);
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.locator(".public-stay-card")).toHaveCount(2);
    expect(requests.at(-1)?.searchParams.getAll("amenity")).toEqual([
      "wifi",
      "kitchen",
    ]);
    expect(requests.at(-1)?.searchParams.get("cursor")).toBe("m8-next");
    const dialog = await openFilters(page);
    await dialog.getByLabel("Minimum", { exact: true }).fill("70");
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    await expect
      .poll(() => requests.at(-1)?.searchParams.get("min_price_minor"))
      .toBe("7000");
    expect(requests.at(-1)?.searchParams.has("cursor")).toBe(false);
  });

  test("duplicate scalar deep links reach validation intact and can be corrected without losing amenity selections", async ({
    page,
  }) => {
    const requests: URL[] = [];
    await fixtures(page, (route, url) => {
      requests.push(url);
      if (url.searchParams.getAll("min_price_minor").length > 1)
        return route.fulfill({
          status: 422,
          json: {
            error: {
              code: "validation_error",
              message: "Repeated scalar filter",
              field_errors: {
                min_price_minor: ["Supply this parameter once."],
              },
            },
          },
        });
      return route.fulfill({
        json: { items: filtered(url.searchParams), next_cursor: null },
      });
    });
    await page.goto(
      "/stays?min_price_minor=6000&min_price_minor=7000&amenity=wifi&amenity=kitchen",
    );
    await expect(page.getByRole("alert")).toContainText(
      "Repeated scalar filter",
    );
    expect(requests.at(-1)?.searchParams.getAll("min_price_minor")).toEqual([
      "6000",
      "7000",
    ]);
    expect(requests.at(-1)?.searchParams.getAll("amenity")).toEqual([
      "wifi",
      "kitchen",
    ]);
    const dialog = await openFilters(page);
    await dialog.getByLabel("Minimum", { exact: true }).fill("70");
    await dialog
      .getByRole("button", { name: "Show stays", exact: true })
      .click();
    await expect(page.locator(".public-stay-card")).toHaveCount(1);
    expect(new URL(page.url()).searchParams.getAll("min_price_minor")).toEqual([
      "7000",
    ]);
    expect(new URL(page.url()).searchParams.getAll("amenity")).toEqual([
      "wifi",
      "kitchen",
    ]);
  });

  test("late main response cannot replace the latest visit to an identical repeated-amenity query", async ({
    page,
  }) => {
    const pending = deferred();
    const release = deferred();
    const oldFinished: Promise<void>[] = [];
    let visitedB = false;
    await fixtures(page, async (route, url) => {
      if (!url.searchParams.has("category") && !visitedB) {
        const finished = deferred();
        oldFinished.push(finished.promise);
        pending.resolve();
        await release.promise;
        await route
          .fulfill({ json: { items: [listings[0]], next_cursor: null } })
          .catch(() => {});
        finished.resolve();
        return;
      }
      if (url.searchParams.has("category")) {
        visitedB = true;
        return route.fulfill({
          json: { items: [listings[1]], next_cursor: null },
        });
      }
      return route.fulfill({
        json: { items: [listings[2]], next_cursor: null },
      });
    });
    await page.goto("/?amenity=wifi&amenity=kitchen");
    await pending.promise;
    await page.getByRole("button", { name: "Cabins", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: listings[1].title, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Homes", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: listings[2].title, exact: true }),
    ).toBeVisible();
    release.resolve();
    await Promise.all(oldFinished);
    await page.waitForTimeout(150);
    await expect(
      page.getByRole("heading", { name: listings[2].title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: listings[0].title, exact: true }),
    ).toHaveCount(0);
    expect(new URL(page.url()).searchParams.getAll("amenity")).toEqual([
      "wifi",
      "kitchen",
    ]);
  });

  test("late pagination from A cannot contaminate a newer A after A to B to A", async ({
    page,
  }) => {
    const pending = deferred();
    const release = deferred();
    const settled = deferred();
    let visitedB = false;
    await fixtures(page, async (route, url) => {
      if (url.searchParams.has("cursor")) {
        pending.resolve();
        await release.promise;
        await route
          .fulfill({ json: { items: [listings[3]], next_cursor: null } })
          .catch(() => {});
        settled.resolve();
        return;
      }
      if (!url.searchParams.has("category")) {
        const items = visitedB ? [listings[2]] : [listings[0]];
        return route.fulfill({ json: { items, next_cursor: "m8-next" } });
      }
      visitedB = true;
      return route.fulfill({
        json: { items: [listings[1]], next_cursor: null },
      });
    });
    await page.goto("/?amenity=wifi&amenity=kitchen");
    await expect(
      page.getByRole("heading", { name: listings[0].title, exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Load more stays", exact: true })
      .click();
    await pending.promise;
    await page.getByRole("button", { name: "Cabins", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: listings[1].title, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Homes", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: listings[2].title, exact: true }),
    ).toBeVisible();
    release.resolve();
    await settled.promise;
    // Allow the deliberately delayed transport and React commit to settle before
    // checking absence; an immediate negative assertion could hide stale data.
    await page.waitForTimeout(150);
    await expect(page.locator(".public-stay-card")).toHaveCount(1);
    await expect(
      page.getByRole("heading", { name: listings[3].title, exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Load more stays", exact: true }),
    ).toBeEnabled();
  });
});
