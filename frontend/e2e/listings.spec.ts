import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { mkdir } from "node:fs/promises";
const evidenceDir = process.env.SMOKE_EVIDENCE_DIR ?? "evidence";
const storageOrigin =
  process.env.SMOKE_STORAGE_ORIGIN ?? "http://localhost:9000";
async function screenshot(page: Page, name: string) {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    if (width === 390)
      await expect(page.locator("aside.host-sidebar")).toHaveCSS(
        "transform",
        "matrix(1, 0, 0, 1, -240, 0)",
      );
    await page.evaluate(() => window.scrollTo(0, 0));
    if (name !== "wizard-basics") {
      await expect
        .poll(() =>
          page
            .locator("main img")
            .evaluateAll(
              (images) =>
                images.length > 0 &&
                images.every(
                  (image) =>
                    (image as HTMLImageElement).complete &&
                    (image as HTMLImageElement).naturalWidth > 0,
                ),
            ),
        )
        .toBe(true);
    }
    await page.screenshot({
      path: `${evidenceDir}/m2-${name}-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
async function imageFiles(page: Page, count: number) {
  return page.evaluate(
    (total) =>
      Array.from({ length: total }, (_, index) => {
        const canvas = document.createElement("canvas");
        canvas.width = 800;
        canvas.height = 600;
        const c = canvas.getContext("2d")!;
        c.fillStyle = ["#e8dfd1", "#dde5dd", "#e6d9c9", "#d8e1e7", "#e8dfda"][
          index % 5
        ];
        c.fillRect(0, 0, 800, 600);
        c.fillStyle = "#c5b49c";
        c.fillRect(0, 410, 800, 190);
        c.fillStyle = "#f7f7f5";
        c.fillRect(60, 60, 280, 280);
        c.fillStyle = "#8eb2c0";
        c.fillRect(75, 75, 250, 250);
        c.fillStyle = "#f7f7f5";
        c.fillRect(196, 75, 8, 250);
        c.fillRect(75, 196, 250, 8);
        c.fillStyle = "#0b6b5d";
        c.fillRect(390, 300, 340, 135);
        c.fillStyle = "#e2f1ee";
        c.fillRect(410, 260, 145, 90);
        c.fillRect(565, 260, 145, 90);
        c.fillStyle = "#665944";
        c.fillRect(410, 435, 15, 25);
        c.fillRect(695, 435, 15, 25);
        c.fillStyle = "#111827";
        c.font = "20px sans-serif";
        c.fillText(`StayHub test photo ${index + 1}`, 60, 550);
        return canvas.toDataURL("image/png").split(",")[1];
      }),
    count,
  );
}
test("real draft, direct upload, recovery, publication, preview and unlisting", async ({
  page,
}) => {
  test.setTimeout(180000);
  await mkdir(evidenceDir, { recursive: true });
  const email = `m2-browser-${Date.now()}-${randomBytes(3).toString("hex")}@example.com`;
  const password = randomBytes(18).toString("base64url");
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("M2 Review Host");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await page.getByRole("button", { name: "Switch to hosting" }).click();
  await page
    .getByRole("button", { name: "Start hosting", exact: true })
    .click();
  await expect(page).toHaveURL(/\/host\/today$/);
  await page.getByRole("link", { name: "Manage listings" }).click();
  await expect(
    page.getByRole("heading", { name: "Make room for your first listing" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "+ Create listing", exact: true })
    .click();
  await expect(page).toHaveURL(/\/host\/listings\/[^/]+\/edit$/);
  const editUrl = page.url();
  await page
    .getByLabel("Property type", { exact: true })
    .selectOption("apartment");
  await page
    .getByLabel("Destination", { exact: true })
    .fill("Lisbon, Portugal");
  await page.getByLabel("Street address").fill("Rua da Bica 22");
  await page.getByLabel("Timezone", { exact: true }).fill("Europe/Lisbon");
  for (const [label, value] of [
    ["Guests", "3"],
    ["Bedrooms", "2"],
    ["Beds", "2"],
    ["Bathrooms", "1"],
  ])
    await page.getByLabel(label, { exact: true }).fill(value);
  await screenshot(page, "wizard-basics");
  await page.getByRole("button", { name: "Save and exit" }).click();
  await expect(page).toHaveURL(/\/host\/listings$/);
  await page.reload();
  await page.getByRole("link", { name: "Resume draft" }).click();
  await expect(page.getByLabel("Destination", { exact: true })).toHaveValue(
    "Lisbon, Portugal",
  );
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page
    .getByLabel("Listing title")
    .fill("Bica apartment with morning light");
  await page
    .getByLabel("Description", { exact: true })
    .fill(
      "A bright apartment close to the river. Two bedrooms, a full kitchen and a quiet place to settle into Lisbon.",
    );
  await page
    .getByLabel("Amenities", { exact: true })
    .fill("Wifi\nKitchen\nAir conditioning");
  const files = await imageFiles(page, 5);
  const putRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT")
      putRequests.push(new URL(request.url()).origin);
  });
  await page.getByLabel("Add photos").setInputFiles(
    files.slice(0, 4).map((file, index) => ({
      name: `room-${index + 1}.png`,
      mimeType: "image/png",
      buffer: Buffer.from(file, "base64"),
    })),
  );
  await expect(
    page.getByText("4 verified · at least 5 to publish · up to 20 photos"),
  ).toBeVisible({ timeout: 60000 });
  await expect(
    page.getByRole("button", { name: "Save and continue" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByLabel("Nightly price (EUR)", { exact: true }).fill("129.05");
  await page.getByLabel("Cleaning fee (EUR)", { exact: true }).fill("35.00");
  await page
    .getByLabel("Cancellation policy", { exact: true })
    .selectOption({ label: "Moderate · v1" });
  await page
    .getByLabel("Booking mode", { exact: true })
    .selectOption("request");
  await page
    .getByLabel("House rules", { exact: true })
    .fill("Quiet after 11 pm\nNo smoking indoors");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page
    .getByRole("button", { name: "Publish listing", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Please check these fields" }),
  ).toContainText("photos");
  await page.getByRole("button", { name: /Photos & content/ }).click();
  await page.getByLabel("Add photos").setInputFiles({
    name: "room-5.png",
    mimeType: "image/png",
    buffer: Buffer.from(files[4], "base64"),
  });
  await expect(
    page.getByText("5 verified · at least 5 to publish · up to 20 photos"),
  ).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole("button", { name: "Save draft" })).toBeEnabled();
  await page.getByRole("button", { name: "Move photo 2 earlier" }).click();
  await expect(page.getByRole("button", { name: "Save draft" })).toBeEnabled();
  await screenshot(page, "wizard-photos");
  await page.getByRole("button", { name: /Review & publish/ }).click();
  await page
    .getByRole("button", { name: "Publish listing", exact: true })
    .click();
  await expect(
    page.getByText("Your listing is published.", { exact: true }),
  ).toBeVisible();
  expect(putRequests).toHaveLength(5);
  expect(putRequests.every((origin) => origin === storageOrigin)).toBe(true);
  await page
    .getByRole("link", { name: "Preview listing", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Bica apartment with morning light",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(5);
  await expect
    .poll(() =>
      page
        .locator(".preview-gallery img")
        .evaluateAll((images) =>
          images.every(
            (image) =>
              (image as HTMLImageElement).complete &&
              (image as HTMLImageElement).naturalWidth > 0,
          ),
        ),
    )
    .toBe(true);
  await screenshot(page, "preview");
  await page.getByRole("link", { name: "Back to listings" }).click();
  await expect(page.getByText("Published", { exact: true })).toBeVisible();
  await screenshot(page, "cards");
  await page.getByRole("link", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: /Photos & content/ }).click();
  await page
    .getByRole("button", { name: "Remove photo 1", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(/unlist/i);
  await page.getByRole("button", { name: "Unlist", exact: true }).click();
  await expect(page.getByText("Unlisted", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Save and exit" }).click();
  await expect(page.getByText("Unlisted", { exact: true })).toBeVisible();
  await page.goto(editUrl);
  await expect(page.getByLabel("Destination", { exact: true })).toHaveValue(
    "Lisbon, Portugal",
  );
  await page.getByRole("button", { name: /Photos & content/ }).click();
  await expect(
    page.getByText("5 verified · at least 5 to publish · up to 20 photos"),
  ).toBeVisible();
});
