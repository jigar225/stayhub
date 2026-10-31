import { test, expect, type Locator, type Page } from "@playwright/test";

function iso(date: Date) {
  return date.toISOString().slice(0, 10);
}
function plusDays(day: string, offset: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return iso(date);
}
function dayName(day: string) {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${day}T12:00:00Z`));
}
async function businessDay(page: Page) {
  const response = await page.request.get("/api/v1/business-time");
  expect(response.status()).toBe(200);
  return (await response.json()).business_now.slice(0, 10) as string;
}
async function showDay(dialog: Locator, day: string) {
  for (let count = 0; count < 36; count++) {
    const button = dialog.locator(`button[data-date="${day}"]`);
    if (await button.count()) {
      await expect(button).toHaveAccessibleName(dayName(day));
      return button;
    }
    const first = await dialog
      .locator("button[data-date]")
      .first()
      .getAttribute("data-date");
    await dialog
      .getByRole("button", {
        name: first! < day ? "Next month" : "Previous month",
        exact: true,
      })
      .click();
  }
  throw new Error(`Could not navigate the local exact-date panel to ${day}`);
}
async function selectRange(page: Page, checkIn: string, checkOut: string) {
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Choose travel dates",
    exact: true,
  });
  await (await showDay(dialog, checkIn)).click();
  await (await showDay(dialog, checkOut)).click();
  return dialog;
}

for (const width of [1440, 1024, 390]) {
  test(`exact calendar commits a year-boundary range and retains filter/category history at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const today = await businessDay(page);
    const year = Number(today.slice(0, 4)) + 1;
    const checkIn = `${year}-12-31`,
      checkOut = `${year + 1}-01-03`;
    await page.goto(
      "/stays?destination=Lisbon&guests=2&category=design&amenity=wifi&amenity=kitchen&min_price_minor=6000",
    );
    const original = page.url();
    const dialog = await selectRange(page, checkIn, checkOut);
    await expect(dialog.getByRole("grid")).toHaveCount(width === 390 ? 1 : 2);
    const panelBox = await dialog.boundingBox();
    expect(panelBox!.x).toBeGreaterThanOrEqual(0);
    expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(width);
    await expect(dialog.getByRole("status")).toContainText("3 nights");
    expect(page.url()).toBe(original);
    await expect(
      dialog.locator(`button[data-date="${checkOut}"]`),
    ).toHaveAttribute("aria-pressed", "true");
    await dialog
      .getByRole("button", { name: "Apply dates", exact: true })
      .click();
    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "Check in", exact: true }),
    ).toContainText(`31 Dec ${year}`);
    expect(page.url()).toBe(original); // Dates are form drafts until Search.
    await page
      .getByRole("button", { name: "Search stays", exact: true })
      .click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("check_in"))
      .toBe(checkIn);
    const committed = new URL(page.url()).searchParams;
    expect(committed.get("check_out")).toBe(checkOut);
    expect(committed.get("category")).toBe("design");
    expect(committed.get("min_price_minor")).toBe("6000");
    expect(committed.getAll("amenity")).toEqual(["wifi", "kitchen"]);
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Check out", exact: true }),
    ).toContainText(`3 Jan ${year + 1}`);
    await page.getByRole("button", { name: "Check out", exact: true }).click();
    const reopened = page.getByRole("dialog", {
      name: "Choose travel dates",
      exact: true,
    });
    await reopened
      .getByRole("button", { name: "Clear dates", exact: true })
      .click();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Check out", exact: true }),
    ).toBeFocused();
    await expect(
      page.getByRole("button", { name: "Check out", exact: true }),
    ).toContainText(`3 Jan ${year + 1}`);
    await page.goBack();
    await expect(
      page.getByRole("button", { name: "Check in", exact: true }),
    ).toContainText("Add dates");
    expect(new URL(page.url()).searchParams.getAll("amenity")).toEqual([
      "wifi",
      "kitchen",
    ]);
    await page.goForward();
    await expect(
      page.getByRole("button", { name: "Check in", exact: true }),
    ).toContainText(`31 Dec ${year}`);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("calendar keyboard traverses days/weeks/months/years, minimum days disable and dismissal restores opener", async ({
  page,
}) => {
  const today = await businessDay(page);
  const year = Number(today.slice(0, 4)) + 1;
  const checkIn = `${year}-12-31`,
    checkOut = `${year + 1}-01-03`;
  await page.goto(`/?check_in=${checkIn}&check_out=${checkOut}`);
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Choose travel dates",
    exact: true,
  });
  await expect(dialog.locator(`button[data-date="${checkIn}"]`)).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(
    dialog.locator(`button[data-date="${year + 1}-01-01"]`),
  ).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(
    dialog.locator(`button[data-date="${year + 1}-01-08"]`),
  ).toBeFocused();
  await page.keyboard.press("PageDown");
  await expect(
    dialog.locator(`button[data-date="${year + 1}-02-08"]`),
  ).toBeFocused();
  await page.keyboard.press("Shift+PageUp");
  await expect(
    dialog.locator(`button[data-date="${year}-02-08"]`),
  ).toBeFocused();
  await page.keyboard.press("Home");
  const focused = await dialog
    .locator("button[data-date]:focus")
    .getAttribute("data-date");
  expect(new Date(`${focused}T12:00:00Z`).getUTCDay()).toBe(1);
  await page.keyboard.press("End");
  const end = await dialog
    .locator("button[data-date]:focus")
    .getAttribute("data-date");
  expect(new Date(`${end}T12:00:00Z`).getUTCDay()).toBe(0);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Check in", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Check out", exact: true }).click();
  await page.locator("#search-guests").click();
  await expect(dialog).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Check out", exact: true }),
  ).toBeFocused();
  await page.goto("/");
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  const old = dialog.locator("button[data-date]:disabled");
  if (await old.count()) await expect(old.first()).toBeDisabled();
  else {
    const firstDay = dialog.locator("button[data-date]:not(:disabled)").first();
    await firstDay.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(firstDay).toBeFocused();
  }
  await dialog
    .getByRole("button", { name: "Clear dates", exact: true })
    .click();
  const available = dialog.locator("button[data-date]:not(:disabled)").first();
  await available.focus();
  await page.keyboard.press("Enter");
  await expect(available).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Space");
  await expect(dialog.getByRole("status")).toContainText("1 night");
  await dialog
    .getByRole("button", { name: "Close dates", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Check in", exact: true }),
  ).toBeFocused();
});

test("generic calendar can clear dates; compact detail rejects incomplete dates and hides a stale quote", async ({
  page,
}) => {
  const today = await businessDay(page);
  const checkIn = plusDays(today, 90),
    checkOut = plusDays(today, 93);
  await page.goto(`/?check_in=${checkIn}&check_out=${checkOut}&amenity=wifi`);
  let dialog = await selectRange(page, checkIn, checkOut);
  await dialog
    .getByRole("button", { name: "Clear dates", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Apply dates", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Check in", exact: true }),
  ).toContainText("Add dates");
  await page.getByRole("button", { name: "Search stays", exact: true }).click();
  expect(new URL(page.url()).searchParams.has("check_in")).toBe(false);
  expect(new URL(page.url()).searchParams.getAll("amenity")).toEqual(["wifi"]);
  const listingResponse = await page.request.get(
    `/api/v1/listings?check_in=${checkIn}&check_out=${checkOut}&guests=1&limit=100`,
  );
  expect(listingResponse.status()).toBe(200);
  const listing = (await listingResponse.json()).items[0] as { id: string };
  expect(listing).toBeTruthy();
  await page.goto(
    `/stays/${listing.id}?check_in=${checkIn}&check_out=${checkOut}&guests=1&category=design&amenity=wifi&amenity=kitchen&min_price_minor=6000&cursor=stale`,
  );
  await expect(
    page.getByRole("link", { name: "Reserve", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  dialog = page.getByRole("dialog", {
    name: "Choose travel dates",
    exact: true,
  });
  await dialog
    .getByRole("button", { name: "Clear dates", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Apply dates", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Choose both");
  await expect(dialog).toBeVisible();
  await (await showDay(dialog, plusDays(checkIn, 1))).click();
  await (await showDay(dialog, plusDays(checkOut, 1))).click();
  await dialog
    .getByRole("button", { name: "Apply dates", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Reserve", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Check price", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Reserve", exact: true }),
  ).toBeVisible();
  const updated = new URL(page.url()).searchParams;
  expect(updated.get("check_in")).toBe(plusDays(checkIn, 1));
  expect(updated.get("category")).toBe("design");
  expect(updated.getAll("amenity")).toEqual(["wifi", "kitchen"]);
  expect(updated.get("min_price_minor")).toBe("6000");
  expect(updated.has("cursor")).toBe(false);
});
