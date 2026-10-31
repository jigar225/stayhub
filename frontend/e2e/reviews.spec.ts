import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const evidence = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";

async function login(page: Page, role: "GUEST" | "HOST") {
  const email = process.env[`SEED_${role}_EMAIL`];
  const password = process.env[`SEED_${role}_PASSWORD`];
  if (!email || !password)
    throw new Error(
      `Private ${role.toLowerCase()} test credentials are required.`,
    );
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  await expect(page).toHaveURL(/\/profile$/);
  return (await result.json()).access_token as string;
}

async function capture(page: Page, label: string) {
  await mkdir(evidence, { recursive: true });
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${evidence}/v2b-${label}-${width}.png`,
      fullPage: true,
    });
  }
}

test("real completed guest and host submit double-blind reviews with notification deep links", async ({
  page,
  browser,
}) => {
  const rid = process.env.SMOKE_REVIEW_ID;
  const lid = process.env.SMOKE_REVIEW_LISTING_ID;
  if (!rid || !lid || process.env.SMOKE_ISOLATED_BASE_URL !== origin)
    throw new Error("Explicit isolated completed review fixture is required.");
  const path = `/trips/${rid}/review`;
  const guestText = `Fictional automated review for isolated reservation ${rid}. The saved stay details matched our visit.`;
  const hostText = `Fictional automated host review for isolated reservation ${rid}. The guest respected the house rules.`;
  const hostContext = await browser.newContext({ baseURL: origin });
  const hostPage = await hostContext.newPage();
  try {
    const guestToken = await login(page, "GUEST");
    const hostToken = await login(hostPage, "HOST");
    const publicBefore = await (
      await page.request.get(`/api/v1/listings/${lid}/reviews`)
    ).json();
    const financialBefore = await (
      await page.request.get(`/api/v1/reservations/${rid}`, {
        headers: { Authorization: `Bearer ${guestToken}` },
      })
    ).json();
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: "Review your stay", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Rate your stay", { exact: true }),
    ).toBeVisible();
    for (const rating of await page.getByRole("combobox").all())
      await rating.selectOption("5");
    await page.getByLabel("Public review", { exact: true }).fill(guestText);
    await expect(
      page.getByRole("button", { name: "Submit review", exact: true }),
    ).toBeDisabled();
    await page.getByRole("checkbox", { name: /cannot be edited/ }).check();
    await capture(page, "review-form");
    await page
      .getByRole("button", { name: "Submit review", exact: true })
      .click();
    await expect(page.getByText(/Saved privately/)).toBeVisible();
    const hidden = await hostPage.request.get(
      `/api/v1/reservations/${rid}/reviews`,
      { headers: { Authorization: `Bearer ${hostToken}` } },
    );
    expect(hidden.status()).toBe(200);
    const hiddenBody = await hidden.json();
    expect(hiddenBody.counterpart).toBeNull();
    expect(JSON.stringify(hiddenBody)).not.toContain(guestText);
    const publicHidden = await (
      await page.request.get(`/api/v1/listings/${lid}/reviews`)
    ).json();
    expect(publicHidden.count).toBe(publicBefore.count);
    await hostPage.goto(path);
    await expect(
      hostPage.getByLabel("Review of your guest", { exact: true }),
    ).toBeVisible();
    await expect(hostPage.getByRole("combobox")).toHaveCount(0);
    await expect(hostPage.getByText(guestText, { exact: true })).toHaveCount(0);
    await hostPage
      .getByLabel("Review of your guest", { exact: true })
      .fill(hostText);
    await hostPage.getByRole("checkbox", { name: /cannot be edited/ }).check();
    await hostPage
      .getByRole("button", { name: "Submit review", exact: true })
      .click();
    await expect(hostPage.getByText(guestText, { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Refresh review status", exact: true })
      .click();
    await expect(page.getByText(hostText, { exact: true })).toBeVisible();
    await capture(page, "published-reviews");
    const published = await (
      await page.request.get(`/api/v1/listings/${lid}/reviews`)
    ).json();
    expect(published.count).toBe(publicBefore.count + 1);
    expect(published.average).not.toBeNull();
    expect(
      published.items.some(
        (review: { text: string; author_role: string; overall: number }) =>
          review.text === guestText &&
          review.author_role === "guest" &&
          review.overall === 5,
      ),
    ).toBe(true);
    expect(
      published.items.some(
        (review: { text: string }) => review.text === hostText,
      ),
    ).toBe(false);
    const financialAfter = await (
      await page.request.get(`/api/v1/reservations/${rid}`, {
        headers: { Authorization: `Bearer ${guestToken}` },
      })
    ).json();
    for (const field of [
      "state",
      "financial_version",
      "host_entitlement_minor",
      "platform_entitlement_minor",
      "payment",
      "refund",
      "payout",
    ])
      expect(financialAfter.reservation[field]).toEqual(
        financialBefore.reservation[field],
      );
    await page.goto(`/stays/${lid}`);
    await expect(
      page.getByRole("heading", { name: "Guest reviews", exact: true }),
    ).toBeVisible();
    await expect(page.getByText(guestText, { exact: true })).toBeVisible();
    await page.goto("/notifications");
    const publicationLink = page
      .getByRole("link", {
        name: "Reservation reviews are published",
        exact: true,
      })
      .and(page.locator(`a[href="${path}"]`));
    await expect(publicationLink).toBeVisible();
    await publicationLink.click();
    await expect(page).toHaveURL(new RegExp(`/trips/${rid}/review$`));
    await expect(page.getByText(hostText, { exact: true })).toBeVisible();
    await page.goto("/notifications");
    await expect(
      page.getByRole("heading", { name: "Notifications", exact: true }),
    ).toBeVisible();
    const markOne = page.getByRole("button", { name: /^Mark read:/ });
    if (await markOne.count()) await markOne.first().click();
    const markAll = page.getByRole("button", {
      name: "Mark all read",
      exact: true,
    });
    if (await markAll.isEnabled()) await markAll.click();
    await expect(page.getByText("0 unread", { exact: true })).toBeVisible();
    await capture(page, "notifications");
  } finally {
    await hostContext.close();
  }
});
