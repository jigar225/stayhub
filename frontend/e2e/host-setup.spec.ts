import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const dir = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";
test("real host timezone search preserves aliases and all policy terms at release widths", async ({
  page,
}) => {
  expect(
    process.env.SMOKE_ISOLATED_BASE_URL,
    "Use the explicitly isolated review stack",
  ).toBe(origin);
  expect(new URL(origin).hostname).toBe("localhost");
  await mkdir(dir, { recursive: true });
  const login = await page.request.post("/api/v1/auth/login", {
    headers: { Origin: origin },
    data: {
      email: process.env.SEED_HOST_EMAIL,
      password: process.env.SEED_HOST_PASSWORD,
    },
  });
  expect(login.status()).toBe(200);
  const headers = {
    Authorization: `Bearer ${(await login.json()).access_token}`,
    Origin: origin,
  };
  const create = await page.request.post("/api/v1/host/listings", {
    headers,
    data: {},
  });
  expect(create.status()).toBe(201);
  let draft = (await create.json()).listing;
  const update = await page.request.patch(`/api/v1/host/listings/${draft.id}`, {
    headers,
    data: {
      version: draft.version,
      timezone: "US/Eastern",
      title: "V2B host setup browser draft",
    },
  });
  expect(update.status()).toBe(200);
  draft = (await update.json()).listing;
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto(`/host/listings/${draft.id}/edit`);
    const timezone = page.getByRole("combobox", {
      name: "Timezone",
      exact: true,
    });
    if (width === 390) await expect(timezone).toHaveValue("US/Eastern");
    await timezone.fill("kolkata");
    await expect(
      page.getByRole("option", { name: "Asia/Kolkata — Kolkata", exact: true }),
    ).toBeVisible();
    await timezone.press("ArrowDown");
    await timezone.press("Enter");
    await expect(timezone).toHaveValue("Asia/Kolkata");
    await page.screenshot({
      path: `${dir}/host-timezone-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(
      page.getByText("All changes saved", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(timezone).toHaveValue("Asia/Kolkata");
    await page.getByRole("button", { name: /Pricing & rules/ }).click();
    const policy = page.getByLabel("Cancellation policy", { exact: true });
    for (const name of ["Flexible", "Moderate", "Firm", "Strict"])
      await expect(
        policy.getByRole("option", { name: `${name} · v1`, exact: true }),
      ).toHaveCount(1);
    const strict = await policy
      .getByRole("option", { name: "Strict · v1", exact: true })
      .getAttribute("value");
    await policy.selectOption(strict!);
    await expect(page.locator(".selected-policy-summary")).toContainText(
      "48 hours after booking",
    );
    await expect(page.locator(".selected-policy-summary")).toContainText(
      "Cleaning fees are fully refunded",
    );
    await page.screenshot({
      path: `${dir}/host-policies-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
