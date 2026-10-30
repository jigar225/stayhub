import { test, expect } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { mkdir } from "node:fs/promises";
test("real signup, profile, hosting, reload, logout and protected deep link", async ({
  page,
}) => {
  await mkdir("evidence", { recursive: true });
  const email = `m1-browser-${Date.now()}-${randomBytes(3).toString("hex")}@example.com`;
  const password = randomBytes(18).toString("base64url");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Find a place to stay" }),
    ).toBeVisible();
    await page.screenshot({
      path: `evidence/guest-${width}.png`,
      fullPage: true,
    });
    await page.goto("/login");
    await page.screenshot({
      path: `evidence/auth-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("Milestone Review Guest");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const signupLogin = page.waitForResponse(
    (response) =>
      response.url().endsWith("/auth/login") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const originalAccess = (
    (await (await signupLogin).json()) as { access_token: string }
  ).access_token;
  await expect(page).toHaveURL(/\/profile$/);
  await expect(
    page.getByRole("definition").filter({ hasText: email }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Profile", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.goto("/host/today");
  await expect(
    page.getByRole("heading", { name: "Access is limited" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "View your profile" }).click();
  await page.getByRole("button", { name: "Switch to hosting" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("button", { name: "Start hosting", exact: true })
    .click();
  await expect(page).toHaveURL(/\/host\/today$/);
  await expect(
    page.getByRole("heading", { name: "No pending requests" }),
  ).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForFunction(() => {
      const sidebar = document.querySelector(".host-sidebar");
      if (!sidebar) return true;
      const { left } = sidebar.getBoundingClientRect();
      return window.innerWidth > 760
        ? left === 0
        : left <= -sidebar.clientWidth;
    });
    await page.screenshot({
      path: `evidence/host-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.getByRole("button", { name: "Open hosting navigation" }).click();
  await expect(
    page.getByRole("dialog", { name: "Hosting navigation" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open hosting navigation" }),
  ).toBeFocused();
  const hostingDrawer = page.getByRole("dialog", {
    name: "Hosting navigation",
  });
  await page.getByRole("button", { name: "Open hosting navigation" }).click();
  await hostingDrawer.getByRole("link", { name: /Calendar/ }).click();
  await expect(
    page.getByRole("heading", { name: "Calendar", exact: true }),
  ).toBeVisible();
  await page.goto("/host/today");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Today", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Switch to traveling" }).click();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("link", { name: "Profile", exact: true }).click();
  await expect(
    page.getByRole("definition").filter({ hasText: "Guest · Host" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Log in", exact: true }),
  ).toBeVisible();
  const revoked = await page.request.get("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${originalAccess}` },
  });
  expect(revoked.status()).toBe(401);
  await page.goto("/profile");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("invalid-password");
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
});

test("invalid signup fields stay local and can be corrected", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/auth\/(register|login)$/.test(new URL(request.url()).pathname)
    )
      requests.push(request.url());
  });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/signup");
  const name = page.getByLabel("Full name");
  const email = page.getByLabel("Email address");
  const password = page.getByLabel("Password", { exact: true });
  const submit = page.getByRole("button", { name: "Create account" });
  await name.fill("Review Guest");
  await email.fill("invalid-email");
  await password.fill("valid-password");
  await submit.click();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(email).toBeFocused();
  expect(requests).toHaveLength(0);
  await email.fill(`validation-${randomBytes(8).toString("hex")}@example.com`);
  await password.fill("elevenchars");
  await submit.click();
  await expect(password).toHaveAttribute("aria-invalid", "true");
  await expect(password).toBeFocused();
  expect(requests).toHaveLength(0);
  await password.fill("valid-password");
  await name.fill("   ");
  await submit.click();
  await expect(name).toHaveAttribute("aria-invalid", "true");
  await expect(name).toBeFocused();
  expect(requests).toHaveLength(0);
  await mkdir("evidence", { recursive: true });
  await page.screenshot({
    path: "evidence/auth-field-validation-390.png",
    fullPage: true,
  });
  await name.fill(" Review Guest ");
  await submit.click();
  await expect(page).toHaveURL(/\/profile$/);
  expect(requests).toHaveLength(2);
});
