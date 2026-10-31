import { test, expect, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chooseDateRange } from "./date-helpers";

const evidence = path.resolve(
  process.env.VISUAL_EVIDENCE_DIR ?? "../evidence/m7",
);
const titles = [
  "Azulejo Loft in Alfama",
  "Riverside studio",
  "Garden house in Sintra",
  "Bica apartment with tram view",
  "Palm-shaded villa",
  "Courtyard retreat",
  "Quiet coastal cottage",
  "Tea-house room",
];
const assets = ["16978555", "10168692", "4468806", "10161222", "16051414"];
const listings = titles.map((title, index) => ({
  id: `m7-isolated-${index}`,
  title,
  destination: index === 2 ? "Sintra" : "Lisbon",
  property_type: "home",
  capacity: 4,
  bedrooms: 2,
  beds: 2,
  baths: 1,
  nightly_minor: 12800 + index * 1000,
  cleaning_minor: 0,
  booking_mode: "instant",
  photos: [
    {
      id: `photo-${index}`,
      url: `/m7-fixture/${assets[index % assets.length]}.jpg`,
      expires_at: "2030-01-01T00:00:00Z",
      width: 1280,
      height: 850,
    },
  ],
  stay_price: null,
  demo_label: "Illustrative demo stay",
  categories: index % 2 === 0 ? ["design"] : ["cabins"],
}));
async function fixtures(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/csrf"))
      return route.fulfill({ json: { csrf_token: "isolated" } });
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
      const category = url.searchParams.get("category");
      const items = category
        ? listings.filter((item) => item.categories.includes(category))
        : listings;
      return route.fulfill({ json: { items, next_cursor: null } });
    }
    throw new Error(`Unmatched isolated API request: ${url.pathname}`);
  });
  await page.route("**/m7-fixture/*.jpg", (route) =>
    route.fulfill({
      path: path.resolve(
        `../demo/assets/pexels-${path.basename(new URL(route.request().url()).pathname)}`,
      ),
      contentType: "image/jpeg",
    }),
  );
}
async function ready(page: Page) {
  await expect(page.locator(".public-stay-card").first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.querySelectorAll("main img")).map((image) =>
        (image as HTMLImageElement).decode(),
      ),
    );
  });
}
async function capture(page: Page, stage: string) {
  await mkdir(evidence, { recursive: true });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await ready(page);
    await page.screenshot({
      path: path.join(evidence, `${stage}-${viewport.width}.png`),
    });
    if (stage === "after")
      await expect(page).toHaveScreenshot(`homepage-${viewport.width}.png`, {
        maxDiffPixels: 0,
        threshold: 0,
      });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const geometry = await page.evaluate(() =>
      Object.fromEntries(
        [
          ".guest-header",
          ".page-heading",
          ".stay-search",
          ".stay-categories",
          ".results-heading",
          ".public-stay-grid",
          ".public-stay-card",
          ".public-cover",
        ].map((selector) => {
          const element = document.querySelector(selector);
          const rect = element?.getBoundingClientRect();
          return [
            selector,
            rect
              ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
              : null,
          ];
        }),
      ),
    );
    await writeFile(
      path.join(evidence, `${stage}-${viewport.width}-geometry.json`),
      JSON.stringify(geometry, null, 2),
    );
  }
}
test("homepage isolated visual evidence", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  await capture(page, process.env.M7_CAPTURE_STAGE ?? "after");
});

test("category browsing composes search and history with honest empty states", async ({
  page,
}) => {
  await fixtures(page);
  await page.goto(
    "/?destination=Lisbon&check_in=2027-02-01&check_out=2027-02-04&guests=2",
  );
  await ready(page);
  await page.getByRole("button", { name: "Design", exact: true }).click();
  await expect(page).toHaveURL(/category=design/);
  await expect(page.locator(".public-stay-card")).toHaveCount(4);
  for (const [key, value] of Object.entries({
    destination: "Lisbon",
    check_in: "2027-02-01",
    check_out: "2027-02-04",
    guests: "2",
  }))
    expect(new URL(page.url()).searchParams.get(key)).toBe(value);
  await page.getByRole("button", { name: "Cabins", exact: true }).click();
  await expect(page.locator(".public-stay-card")).toHaveCount(4);
  await expect(
    page.getByRole("heading", { name: "Riverside studio", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/category=design/);
  await expect(
    page.getByRole("heading", { name: "Azulejo Loft in Alfama", exact: true }),
  ).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/category=cabins/);
  await page.getByRole("button", { name: "Beachfront", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No stays match your plans" }),
  ).toBeVisible();
  await expect(page.locator(".public-stay-card")).toHaveCount(0);
  await page.getByRole("button", { name: "Homes", exact: true }).click();
  expect(new URL(page.url()).searchParams.has("category")).toBe(false);
  await expect(page.locator(".public-stay-card")).toHaveCount(8);
});

test("Who remains keyboard usable and submits validated guests with the category", async ({
  page,
}) => {
  await fixtures(page);
  await page.goto("/?category=design");
  await ready(page);
  await page.getByLabel("Where", { exact: true }).fill("Lisbon");
  await chooseDateRange(page, "2027-02-01", "2027-02-04");
  const guests = page.locator('[name="guests"]');
  await guests.focus();
  await guests.fill("3");
  await guests.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/stays\?/);
  const params = new URL(page.url()).searchParams;
  expect(Object.fromEntries(params)).toMatchObject({
    destination: "Lisbon",
    check_in: "2027-02-01",
    check_out: "2027-02-04",
    guests: "3",
    category: "design",
  });
});

test("late category responses cannot overwrite a newer selection", async ({
  page,
}) => {
  await fixtures(page);
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const pending = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/api/v1/listings?**", async (route) => {
    const category = new URL(route.request().url()).searchParams.get(
      "category",
    );
    if (category !== "design") return route.fallback();
    started();
    await delayed;
    await route
      .fulfill({ json: { items: [listings[0]], next_cursor: null } })
      .catch(() => {});
  });
  await page.goto("/");
  await ready(page);
  await page.getByRole("button", { name: "Design", exact: true }).click();
  await pending;
  await page.getByRole("button", { name: "Cabins", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Riverside studio", exact: true }),
  ).toBeVisible();
  release();
  await expect(page.locator(".public-stay-card")).toHaveCount(4);
  await expect(
    page.getByRole("heading", { name: "Azulejo Loft in Alfama", exact: true }),
  ).toHaveCount(0);
});

test("discovery errors retry and category pagination retains the filter", async ({
  page,
}) => {
  await fixtures(page);
  let failRequests = true;
  const requests: URL[] = [];
  await page.route("**/api/v1/listings?**", (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    if (failRequests) {
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: "unavailable",
            message: "Isolated discovery failure",
            field_errors: null,
          },
        },
      });
    }
    return route.fulfill({
      json: {
        items: url.searchParams.has("cursor") ? [listings[2]] : [listings[0]],
        next_cursor: url.searchParams.has("cursor") ? null : "isolated-next",
      },
    });
  });
  await page.goto("/?category=design&guests=2");
  await expect(page.getByRole("alert")).toContainText(
    "Isolated discovery failure",
  );
  failRequests = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator(".public-stay-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Load more stays" }).click();
  await expect(page.locator(".public-stay-card")).toHaveCount(2);
  expect(requests.at(-1)?.searchParams.get("category")).toBe("design");
  expect(requests.at(-1)?.searchParams.get("guests")).toBe("2");
  expect(requests.at(-1)?.searchParams.get("cursor")).toBe("isolated-next");
});

test("every displayed category submits its explicit data tag", async ({
  page,
}) => {
  await fixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await ready(page);
  for (const [label, slug] of [
    ["Beachfront", "beachfront"],
    ["Amazing views", "amazing-views"],
    ["Cabins", "cabins"],
    ["Design", "design"],
    ["Farms", "farms"],
    ["Tiny homes", "tiny-homes"],
    ["Pools", "pools"],
    ["Off-grid", "off-grid"],
    ["Historic", "historic"],
  ]) {
    const control = page.getByRole("button", { name: label, exact: true });
    await control.click();
    await expect(control).toHaveAttribute("aria-pressed", "true");
    expect(new URL(page.url()).searchParams.get("category")).toBe(slug);
    if (slug === "cabins" || slug === "design")
      await expect(page.locator(".public-stay-card")).toHaveCount(4);
    else
      await expect(
        page.getByRole("heading", { name: "No stays match your plans" }),
      ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
