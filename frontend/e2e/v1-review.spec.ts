import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
async function capture(page: Page, name: string) {
  await mkdir("evidence", { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    if (
      width === 390 &&
      (await page.locator("aside.host-sidebar").count()) &&
      !page.url().endsWith("/admin")
    )
      await expect(page.locator("aside.host-sidebar")).toHaveCSS(
        "transform",
        "matrix(1, 0, 0, 1, -240, 0)",
      );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `evidence/m6-${name}-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
async function seed(role: "HOST" | "ADMIN") {
  const env = await readFile(new URL("../../.env", import.meta.url), "utf8");
  const values = Object.fromEntries(
    env
      .split("\n")
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [
          line.slice(0, i),
          line.slice(i + 1).replace(/^['"]|['"]$/g, ""),
        ];
      }),
  );
  return {
    email: values[`SEED_${role}_EMAIL`],
    password: values[`SEED_${role}_PASSWORD`],
  };
}
async function login(page: Page, role: "HOST" | "ADMIN") {
  const credentials = await seed(role);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  const auth = await (await response).json();
  await expect(page).toHaveURL(/\/profile$/);
  return auth as { access_token: string; csrf_token: string };
}
test("real read loading, empty/error retry, role denial and revoked-session return", async ({
  page,
}) => {
  test.setTimeout(120000);
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("M6 Recovery Review Guest");
  await page
    .getByLabel("Email address")
    .fill(`m6-${randomBytes(8).toString("hex")}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill(randomBytes(18).toString("base64url"));
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const auth = await (await response).json();
  await expect(page).toHaveURL(/\/profile$/);
  let release!: () => void;
  const gate = new Promise<void>((done) => {
    release = done;
  });
  await page.route("**/api/v1/me/reservations?**", async (route) => {
    const real = await route.fetch();
    await gate;
    await route.fulfill({ response: real });
  });
  await page.goto("/trips");
  await expect(page.getByRole("status")).toContainText("Loading trips");
  await capture(page, "trips-loading");
  release();
  await expect(
    page.getByRole("heading", { name: "No trips in this category" }),
  ).toBeVisible();
  await capture(page, "trips-empty");
  await page.unroute("**/api/v1/me/reservations?**");
  await page.route("**/api/v1/me/reservations?**", (route) =>
    route.abort("failed"),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toBeVisible();
  await capture(page, "trips-error");
  await page.unroute("**/api/v1/me/reservations?**");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { name: "No trips in this category" }),
  ).toBeVisible();
  for (const path of ["/host/earnings", "/admin"]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: "Access is limited" }),
    ).toBeVisible();
  }
  for (const path of ["/host/earnings", "/admin/events", "/admin/demo/clock"]) {
    const denied = await page.request.get(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${auth.access_token}` },
    });
    expect(denied.status()).toBe(403);
  }
  const revoked = await page.request.post("/api/v1/auth/logout", {
    headers: {
      Origin: "http://localhost:5173",
      "X-CSRF-Token": auth.csrf_token,
    },
  });
  expect(revoked.status()).toBe(204);
  await page.goto("/trips?category=pending");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(
    "/trips?category=pending",
  );
  const invalid = await page.request.get("/api/v1/me/reservations", {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  });
  expect(invalid.status()).toBe(401);
  await capture(page, "session-recovery");
});
test("owning Host and limited Admin recover real read errors without changing records", async ({
  page,
  browser,
}) => {
  const hostAuth = await login(page, "HOST");
  await page.route("**/api/v1/host/earnings**", (route) =>
    route.abort("failed"),
  );
  await page.goto("/host/earnings");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.unroute("**/api/v1/host/earnings**");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { name: "Paid", exact: true }),
  ).toBeVisible();
  await capture(page, "earnings");
  const noAdmin = await page.request.get("/api/v1/admin/events", {
    headers: { Authorization: `Bearer ${hostAuth.access_token}` },
  });
  expect(noAdmin.status()).toBe(403);
  const context = await browser.newContext();
  const admin = await context.newPage();
  await login(admin, "ADMIN");
  await admin.route("**/api/v1/admin/events?**", (route) =>
    route.abort("failed"),
  );
  await admin.goto("/admin");
  await expect(admin.getByRole("alert")).toBeVisible();
  await admin.unroute("**/api/v1/admin/events?**");
  await admin.getByRole("button", { name: "Try again" }).click();
  await expect(
    admin.getByRole("table", { name: "Recorded events" }),
  ).toBeVisible();
  await expect(
    admin.getByText("Demo advancement is disabled in this environment."),
  ).toBeVisible();
  await admin
    .getByLabel("Action")
    .fill(`nonexistent.m6.${randomBytes(8).toString("hex")}`);
  await admin.getByRole("button", { name: "Filter events" }).click();
  await expect(
    admin.getByRole("heading", { name: "No matching events" }),
  ).toBeVisible();
  await capture(admin, "admin-empty");
  await context.close();
});

test("payout status colours follow the approved semantic tokens", async ({
  page,
}) => {
  await page.goto("/");
  const colours = await page.evaluate(() =>
    ["held", "cancelled"].map((status) => {
      const badge = document.createElement("span");
      badge.className = `reservation-status ${status}`;
      document.body.append(badge);
      const colour = getComputedStyle(badge).color;
      badge.remove();
      return colour;
    }),
  );
  expect(colours).toEqual(["rgb(133, 77, 14)", "rgb(185, 28, 28)"]);
});
