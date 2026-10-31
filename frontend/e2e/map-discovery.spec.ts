import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const evidence = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";

test("real map batch, overlaps, prices, viewport, filters and history at release widths", async ({
  page,
}) => {
  test.setTimeout(120000);
  await mkdir(evidence, { recursive: true });
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
  const policies = await (
    await page.request.get("/api/v1/host/cancellation-policies", { headers })
  ).json();
  const owned = await (
    await page.request.get("/api/v1/host/listings?limit=100", { headers })
  ).json();
  for (const item of owned.items) {
    if (
      item.description === "Explicitly fictional automated map fixture." &&
      item.status === "published"
    ) {
      await page.request.post(`/api/v1/host/listings/${item.id}/unlist`, {
        headers,
        data: { version: item.version },
      });
    }
  }
  const clock = await (await page.request.get("/api/v1/business-time")).json();
  const arrivalDate = new Date(clock.business_now);
  arrivalDate.setUTCDate(arrivalDate.getUTCDate() + 45);
  const departureDate = new Date(arrivalDate);
  departureDate.setUTCDate(departureDate.getUTCDate() + 2);
  const arrival = arrivalDate.toISOString().slice(0, 10),
    departure = departureDate.toISOString().slice(0, 10);
  const ids: string[] = [];
  await page.goto("/stays");
  const image = Buffer.from(
    await page.evaluate(() => {
      const c = document.createElement("canvas");
      c.width = 800;
      c.height = 600;
      const ctx = c.getContext("2d")!;
      ctx.fillStyle = "#dcebd7";
      ctx.fillRect(0, 0, 800, 600);
      ctx.fillStyle = "#0b6b5d";
      ctx.font = "32px sans-serif";
      ctx.fillText("Fictional map test stay", 60, 250);
      return c.toDataURL("image/png").split(",")[1];
    }),
    "base64",
  );
  try {
    for (let i = 0; i < 3; i++) {
      const create = await page.request.post("/api/v1/host/listings", {
        headers,
        data: {},
      });
      expect(create.status()).toBe(201);
      const listing = (await create.json()).listing;
      ids.push(listing.id);
      const saved = await page.request.patch(
        `/api/v1/host/listings/${listing.id}`,
        {
          headers,
          data: {
            version: listing.version,
            property_type: "apartment",
            address: "Fictional map test address",
            destination: "Map review",
            timezone: "Europe/Lisbon",
            capacity: 3,
            bedrooms: 1,
            beds: 2,
            baths: 1,
            title: `Map review ${["A", "B", "C"][i]}`,
            description: "Explicitly fictional automated map fixture.",
            amenities: ["Wifi"],
            house_rules: ["No smoking"],
            nightly_minor: i === 2 ? 15400 : 12800,
            cleaning_minor: 3500,
            policy_id: policies.items[0].id,
            booking_mode: "instant",
            latitude: i === 2 ? 38.73 : 38.71,
            longitude: i === 2 ? -9.14 : -9.13,
          },
        },
      );
      expect(saved.status()).toBe(200);
      for (let photo = 0; photo < 5; photo++) {
        const intent = await (
          await page.request.post(
            `/api/v1/host/listings/${listing.id}/photos/upload-intents`,
            {
              headers,
              data: { content_type: "image/png", bytes: image.length },
            },
          )
        ).json();
        expect(
          (
            await page.request.put(intent.upload.url, {
              headers: intent.upload.headers,
              data: image,
            })
          ).ok(),
        ).toBe(true);
        expect(
          (
            await page.request.post(
              `/api/v1/host/listings/${listing.id}/photos/${intent.photo_id}/complete`,
              { headers, data: {} },
            )
          ).status(),
        ).toBe(200);
      }
      const latest = (
        await (
          await page.request.get(`/api/v1/host/listings/${listing.id}`, {
            headers,
          })
        ).json()
      ).listing;
      expect(
        (
          await page.request.post(
            `/api/v1/host/listings/${listing.id}/publish`,
            { headers, data: { version: latest.version } },
          )
        ).status(),
      ).toBe(200);
    }
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto(
        `/stays?destination=Map+review&guests=2&check_in=${arrival}&check_out=${departure}`,
      );
      await page.getByRole("button", { name: "Map", exact: true }).click();
      await expect(page.locator(".map-price-pin")).toHaveCount(2);
      await expect(page.getByText("Loading map…", { exact: true })).toHaveCount(
        0,
        { timeout: 25000 },
      );
      await expect(
        page.getByText("Map unavailable", { exact: true }),
      ).toHaveCount(0);
      await page.getByRole("button", { name: /^2 stays ·/ }).click();
      const overlap = page.locator(".map-overlap-picker");
      await expect(overlap.getByRole("button")).toHaveCount(2);
      await overlap.getByRole("button", { name: /Map review B/ }).click();
      await expect(page.locator(".map-stay-preview")).toContainText(
        "Map review B",
      );
      await expect(page.locator(".map-price-pin.selected")).toContainText(
        "€128.00",
      );
      await expect(page.locator(".map-stay-preview a")).toHaveAttribute(
        "href",
        /guests=2/,
      );
      await expect(page.locator(".map-stay-preview a")).toHaveAttribute(
        "href",
        new RegExp(`check_in=${arrival}`),
      );
      await expect(page.locator(".map-stay-preview")).toContainText(
        "€331.74 stay total",
      );
      if (width > 700) {
        expect(
          (await page
            .locator(`[data-listing-id="${ids[2]}"] .public-stay-content`)
            .boundingBox())!.width,
        ).toBeGreaterThan(150);
        expect(
          (await page
            .getByRole("button", { name: "Check in", exact: true })
            .boundingBox())!.width,
        ).toBeGreaterThan(90);

        await page
          .locator(`[data-listing-id="${ids[2]}"]`)
          .getByRole("button", { name: /Show on map/ })
          .click();
        await expect(page.locator(".map-price-pin.selected")).toContainText(
          "€154.00",
        );
      }
      await page.screenshot({
        path: `${evidence}/map-loaded-${width}.png`,
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page
        .getByRole("button", { name: "Search this area", exact: true })
        .click();
      await expect(page).toHaveURL(/west=/);
      const areaURL = page.url();
      await page.getByRole("button", { name: "List", exact: true }).click();
      await expect(page).toHaveURL(/view=list/);
      await page.goBack();
      await expect(page).toHaveURL(areaURL);
      await page.getByRole("button", { name: /^Filters/ }).click();
      await page.getByLabel("Minimum", { exact: true }).fill("150");
      await page
        .getByRole("button", { name: "Show stays", exact: true })
        .click();
      await expect(page.locator(".map-price-pin")).toHaveCount(1);
      await expect(page.locator(".map-price-pin")).toContainText("€154.00");
      const automatic = page.getByRole("checkbox", {
        name: "Search as I move the map",
      });
      await automatic.click();
      await expect(automatic).toBeChecked();
      const canvas = page.locator(".results-map-canvas");
      await canvas.scrollIntoViewIfNeeded();
      const box = await canvas.boundingBox();
      const beforePanWest = new URL(page.url()).searchParams.get("west");
      await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box!.x + box!.width / 2 + 50,
        box!.y + box!.height / 2 + 25,
        { steps: 6 },
      );
      await page.mouse.up();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("west"))
        .not.toBe(beforePanWest);
      const stable = page.url();
      await page.waitForTimeout(900);
      expect(page.url()).toBe(stable);
    }
  } finally {
    for (const id of ids) {
      const response = await page.request.get(`/api/v1/host/listings/${id}`, {
        headers,
      });
      if (response.ok()) {
        const l = (await response.json()).listing;
        if (l.status === "published")
          await page.request.post(`/api/v1/host/listings/${id}/unlist`, {
            headers,
            data: { version: l.version },
          });
      }
    }
  }
});

test("map API and tile failures recover while list browsing preserves filters", async ({
  page,
}) => {
  let failed = true;
  const listing = {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Transport recovery fixture",
    destination: "Lisbon",
    property_type: "apartment",
    capacity: 2,
    bedrooms: 1,
    beds: 1,
    baths: 1,
    nightly_minor: 12800,
    cleaning_minor: 3500,
    booking_mode: "instant",
    photos: [],
    stay_price: null,
    demo_label: null,
    location: { latitude: 38.71, longitude: -9.13 },
  };
  await page.route("**/api/v1/listings?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    if (query.get("map") === "true" && failed)
      await route.fulfill({
        status: 503,
        json: {
          error: {
            code: "unavailable",
            message: "Map search unavailable. Retry.",
            field_errors: null,
            request_id: "fixture",
          },
        },
      });
    else
      await route.fulfill({
        json: { items: [listing], next_cursor: null, map_truncated: false },
      });
  });
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.abort(),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/stays?view=map&amenity=wifi&guests=2");
  await expect(page.getByRole("alert")).toContainText("Map search unavailable");
  failed = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.locator(".map-price-pin")).toHaveCount(1);
  await expect(page.getByText("Map unavailable", { exact: true })).toBeVisible({
    timeout: 25000,
  });
  await page.screenshot({
    path: `${evidence}/map-failure-390.png`,
    fullPage: true,
  });
  await page.unroute("https://tiles.openfreemap.org/**");
  await page.getByRole("button", { name: "Retry map", exact: true }).click();
  await expect(page.getByText("Loading map…", { exact: true })).toHaveCount(0, {
    timeout: 25000,
  });
  await expect(page.getByText("Map unavailable", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: listing.title }),
  ).toBeVisible();
  await expect(page).toHaveURL(/amenity=wifi/);
});

test("late viewport response cannot restore stale pins after a filter change", async ({
  page,
}) => {
  let release: (() => void) | undefined;
  let delayed = false;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/listings?**", async (route) => {
    const q = new URL(route.request().url()).searchParams;
    if (q.has("west") && !q.has("min_price_minor")) {
      delayed = true;
      await held;
    }
    const filtered = q.has("min_price_minor");
    try {
      await route.fulfill({
        json: {
          items: [
            {
              id: filtered
                ? "22222222-2222-4222-8222-222222222222"
                : "11111111-1111-4111-8111-111111111111",
              title: filtered
                ? "Newest filter fixture"
                : "Stale viewport fixture",
              destination: "Lisbon",
              property_type: "apartment",
              capacity: 2,
              bedrooms: 1,
              beds: 1,
              baths: 1,
              nightly_minor: filtered ? 15400 : 12800,
              cleaning_minor: 3500,
              booking_mode: "instant",
              photos: [],
              stay_price: null,
              demo_label: null,
              location: { latitude: 38.71, longitude: -9.13 },
            },
          ],
          next_cursor: null,
          map_truncated: false,
        },
      });
    } catch {
      /* An aborted old request is also the intended outcome. */
    }
  });
  await page.goto("/stays?view=map&guests=2");
  await expect(page.locator(".map-price-pin")).toContainText("€128.00");
  await expect(page.getByText("Loading map…", { exact: true })).toHaveCount(0, {
    timeout: 25000,
  });
  await page
    .getByRole("button", { name: "Search this area", exact: true })
    .click();
  await expect.poll(() => delayed).toBe(true);
  await page.getByRole("button", { name: /^Filters/ }).click();
  await page.getByLabel("Minimum", { exact: true }).fill("150");
  await page.getByRole("button", { name: "Show stays", exact: true }).click();
  await expect(page.locator(".map-price-pin")).toContainText("€154.00");
  release!();
  await expect(
    page.getByRole("heading", { name: "Newest filter fixture" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Stale viewport fixture" }),
  ).toHaveCount(0);
  await expect(page.locator(".map-price-pin")).toContainText("€154.00");
});
