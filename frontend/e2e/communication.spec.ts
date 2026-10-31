import { test, expect, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
const origin = process.env.SMOKE_BASE_URL ?? "http://localhost:5173";
const evidence = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";
async function login(page: Page, role: "GUEST" | "HOST") {
  const email = process.env[`SEED_${role}_EMAIL`];
  const password = process.env[`SEED_${role}_PASSWORD`];
  if (!email || !password)
    throw new Error(`Private ${role.toLowerCase()} credentials required`);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  const token = (await (await response).json()).access_token as string;
  await expect(page).toHaveURL(/\/profile$/);
  return token;
}
test("real guest and host messaging, verified private attachment, unread acknowledgement and dropped-response retry", async ({
  page,
  browser,
}) => {
  test.setTimeout(120000);
  if (
    process.env.SMOKE_ISOLATED_BASE_URL !== origin ||
    new URL(origin).hostname !== "localhost"
  )
    throw new Error(
      "Messaging smoke requires an explicitly isolated localhost base URL",
    );
  await mkdir(evidence, { recursive: true });
  const hostContext = await browser.newContext({ baseURL: origin });
  const hostPage = await hostContext.newPage();
  let rid = "";
  let hostHeaders: Record<string, string> = {};
  try {
    const hostToken = await login(hostPage, "HOST");
    hostHeaders = { Authorization: `Bearer ${hostToken}`, Origin: origin };
    const guestToken = await login(page, "GUEST");
    const guestHeaders = {
      Authorization: `Bearer ${guestToken}`,
      Origin: origin,
    };
    const owned = await (
      await hostPage.request.get("/api/v1/host/listings?limit=100", {
        headers: hostHeaders,
      })
    ).json();
    const listing = owned.items.find(
      (item: { status: string }) => item.status === "published",
    );
    if (!listing)
      throw new Error(
        "The isolated host needs an existing published stay; smoke never provisions or resets data",
      );
    const clock = await (
      await page.request.get("/api/v1/business-time")
    ).json();
    let quoteToken = "";
    const base = new Date(clock.business_now);
    base.setUTCDate(base.getUTCDate() + 60 + Math.floor(Math.random() * 30));
    for (let n = 0; n < 30; n++) {
      const start = new Date(base.getTime() + n * 3 * 86400000);
      const end = new Date(start.getTime() + 2 * 86400000);
      const quote = await page.request.post("/api/v1/booking-quotes", {
        headers: { Origin: origin },
        data: {
          listing_id: listing.id,
          check_in: start.toISOString().slice(0, 10),
          check_out: end.toISOString().slice(0, 10),
          guests: 1,
        },
      });
      if (quote.status() === 200) {
        quoteToken = (await quote.json()).quote.quote_token;
        break;
      }
      if (quote.status() !== 409)
        throw new Error(`Fixture quote rejected HTTP ${quote.status()}`);
    }
    if (!quoteToken)
      throw new Error("No available isolated two-night range found");
    const paid = await page.request.post("/api/v1/reservations", {
      headers: { ...guestHeaders, "Idempotency-Key": randomUUID() },
      data: { quote_token: quoteToken },
    });
    expect(paid.status()).toBe(201);
    const reservation = (await paid.json()).reservation;
    rid = reservation.id;
    const code = reservation.code as string;
    await page.goto(`/messages/${rid}`);
    await expect(
      page.getByRole("heading", { name: listing.title }),
    ).toBeVisible();
    await expect(
      page.getByText(/never pay or share payment details outside/),
    ).toBeVisible();
    const text = `Arrival question ${randomUUID()} <script>not executable</script>`;
    await page.getByLabel("Message", { exact: true }).fill(text);
    let sentKey = "",
      dropped = false;
    const path = `**/api/v1/reservations/${rid}/messages`;
    await page.route(path, async (route) => {
      if (route.request().method() !== "POST" || dropped)
        return route.continue();
      sentKey = route.request().headers()["idempotency-key"];
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      dropped = true;
      await route.abort("failed");
    });
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Retry same message", exact: true }),
    ).toBeVisible();
    await page.unroute(path);
    const retried = page.waitForRequest(
      (r) =>
        r.url().endsWith(`/reservations/${rid}/messages`) &&
        r.method() === "POST",
    );
    await page
      .getByRole("button", { name: "Retry same message", exact: true })
      .click();
    expect((await retried).headers()["idempotency-key"]).toBe(sentKey);
    await expect(page.getByText(text, { exact: true })).toHaveCount(1);
    expect(await page.locator(".message-history script").count()).toBe(0);
    const stored = await (
      await page.request.get(`/api/v1/reservations/${rid}/messages`, {
        headers: guestHeaders,
      })
    ).json();
    expect(
      stored.items.filter((m: { text: string }) => m.text === text),
    ).toHaveLength(1);
    const png = Buffer.from(
      await page.evaluate(() => {
        const canvas = document.createElement("canvas");
        canvas.width = 800;
        canvas.height = 600;
        const ctx = canvas.getContext("2d")!;
        ctx.fillStyle = "#dcebd7";
        ctx.fillRect(0, 0, 800, 600);
        ctx.fillStyle = "#0b6b5d";
        ctx.font = "30px sans-serif";
        ctx.fillText("Fictional private arrival photo", 60, 250);
        return canvas.toDataURL("image/png").split(",")[1];
      }),
      "base64",
    );
    await page.locator('input[type="file"]').setInputFiles({
      name: "arrival-fixture.png",
      mimeType: "image/png",
      buffer: png,
    });
    await expect(page.getByAltText("Photo ready to attach")).toBeVisible();
    await page
      .getByLabel("Message", { exact: true })
      .fill("Verified arrival photo");
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await expect(
      page.getByAltText("Private reservation attachment"),
    ).toBeVisible();
    await hostPage.goto("/messages?role=host");
    const card = hostPage
      .locator(".conversation-card")
      .filter({ hasText: code });
    for (let n = 0; n < 20 && !(await card.count()); n++) {
      const more = hostPage.getByRole("button", {
        name: "Load more conversations",
        exact: true,
      });
      if (!(await more.count())) break;
      await more.click();
    }
    await expect(card).toContainText("2 unread");
    await expect(card).toContainText("Verified arrival photo");
    await card.click();
    await expect(
      hostPage.getByAltText("Private reservation attachment"),
    ).toBeVisible();
    await expect
      .poll(async () => {
        const inbox = await (
          await hostPage.request.get(
            "/api/v1/conversations?role=host&limit=50",
            { headers: hostHeaders },
          )
        ).json();
        const row = inbox.items.find(
          (item: { reservation_id: string }) => item.reservation_id === rid,
        );
        return row?.unread_count;
      })
      .toBe(0);
    const reply = "Thanks, your arrival details are received.";
    await hostPage.getByLabel("Message", { exact: true }).fill(reply);
    await hostPage
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await expect(hostPage.getByText(reply, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(reply, { exact: true })).toBeVisible();
    await expect(
      page.getByAltText("Private reservation attachment"),
    ).toBeVisible();
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `${evidence}/communication-${width}.png`,
        fullPage: true,
      });
    }
    await writeFile(
      `${evidence}/communication-persistence.json`,
      JSON.stringify(
        {
          reservation_id: rid,
          code,
          expected_message_count: 3,
          attachment_count: 1,
        },
        null,
        2,
      ),
    );
  } finally {
    if (rid) {
      const detail = await hostPage.request.get(`/api/v1/reservations/${rid}`, {
        headers: hostHeaders,
      });
      if (detail.ok()) {
        const state = (await detail.json()).reservation.state;
        if (state === "pending")
          await hostPage.request.post(
            `/api/v1/host/reservations/${rid}/decline`,
            {
              headers: { ...hostHeaders, "Idempotency-Key": randomUUID() },
              data: { reason: "Isolated communication smoke complete" },
            },
          );
        else if (state === "confirmed")
          await hostPage.request.post(
            `/api/v1/host/reservations/${rid}/cancel`,
            {
              headers: { ...hostHeaders, "Idempotency-Key": randomUUID() },
              data: { reason: "Isolated communication smoke complete" },
            },
          );
      }
    }
    await hostContext.close();
  }
});
