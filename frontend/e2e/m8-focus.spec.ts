import { test, expect, type Locator, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const evidence = path.resolve("../evidence/m8-corrections/focus");
const teal = "rgb(11, 107, 93)";

async function keyboardReturn(page: Page, control: Locator) {
  await control.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(control).toBeFocused();
  await expect(page.locator("html")).toHaveAttribute(
    "data-input-modality",
    "keyboard",
  );
}
async function noInnerRing(control: Locator) {
  await expect(control).toHaveCSS("outline-width", "0px");
  await expect(control).toHaveCSS("box-shadow", "none");
}
async function ready(page: Page) {
  await expect(page.locator(".public-stay-card").first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images).map((image) =>
        image.decode().catch(() => {}),
      ),
    );
  });
}

for (const width of [1440, 1024, 390]) {
  test(`pointer fields have no inner highlight; keyboard segments stay visible at ${width}`, async ({
    page,
  }) => {
    await mkdir(evidence, { recursive: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    for (const route of ["/", "/stays"]) {
      await page.goto(route);
      await ready(page);
      const name = route === "/" ? "home" : "results";
      for (const id of ["guests", "destination"]) {
        const control = page.locator(`#search-${id}`);
        const segment = control.locator(
          "xpath=ancestor::*[contains(@class,'search-field')][1]",
        );
        const before = await segment.boundingBox();
        await control.click();
        await control.fill(id === "guests" ? "2" : "Lisbon");
        await expect(page.locator("html")).toHaveAttribute(
          "data-input-modality",
          "pointer",
        );
        await noInnerRing(control);
        await expect(segment).toHaveCSS("outline-width", "0px");
        await expect(segment).toHaveCSS("box-shadow", "none");
        await keyboardReturn(page, control);
        await noInnerRing(control);
        await expect(segment).toHaveCSS("outline-color", teal);
        await expect(segment).toHaveCSS("outline-width", "2px");
        // A new pointer action removes the keyboard segment ring even if the
        // input stays focused and Chromium still considers it :focus-visible.
        await control.click();
        await expect(control).toBeFocused();
        await expect(page.locator("html")).toHaveAttribute(
          "data-input-modality",
          "pointer",
        );
        await expect(segment).toHaveCSS("outline-width", "0px");
        await noInnerRing(control);
        const after = await segment.boundingBox();
        expect(after?.width).toBe(before?.width);
        expect(after?.height).toBe(before?.height);
      }
      const guests = page.locator("#search-guests");
      await keyboardReturn(page, guests);
      await page.screenshot({
        path: `${evidence}/keyboard-guests-${name}-${width}.png`,
      });
      const checkIn = page.getByRole("button", {
        name: "Check in",
        exact: true,
      });
      await checkIn.click();
      await noInnerRing(checkIn);
      await expect(
        checkIn.locator(
          "xpath=ancestor::*[contains(@class,'search-field')][1]",
        ),
      ).toHaveCSS("outline-width", "0px");
      await expect(
        page.getByRole("dialog", { name: "Choose travel dates", exact: true }),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(checkIn).toBeFocused();
      await noInnerRing(checkIn);
      await expect(
        checkIn.locator(
          "xpath=ancestor::*[contains(@class,'search-field')][1]",
        ),
      ).toHaveCSS("outline-color", teal);
      await expect(checkIn.locator("svg")).toHaveAttribute("width", "20");
      await expect(checkIn.locator("svg")).toHaveAttribute("height", "20");
      await guests.click();
      await guests.fill("0");
      await page
        .getByRole("button", { name: "Search stays", exact: true })
        .click();
      await expect(guests).toHaveAttribute("aria-invalid", "true");
      await expect(guests).toHaveCSS("border-bottom-color", "rgb(185, 28, 28)");
      await page.getByRole("button", { name: /^Filters/ }).click();
      const drawer = page.getByRole("dialog", { name: "Filters", exact: true });
      await expect(drawer).toHaveCSS("box-shadow", "none");
      const minimum = drawer.getByLabel("Minimum", { exact: true });
      const money = minimum.locator(
        "xpath=ancestor::*[contains(@class,'filter-money')][1]",
      );
      await minimum.click();
      await minimum.fill("60.10");
      await noInnerRing(minimum);
      await expect(money).toHaveCSS("outline-width", "0px");
      await keyboardReturn(page, minimum);
      await noInnerRing(minimum);
      await expect(money).toHaveCSS("outline-color", teal);
      await expect(money).toHaveCSS("outline-width", "2px");
      await page.screenshot({
        path: `${evidence}/keyboard-drawer-${name}-${width}.png`,
      });
      await page.keyboard.press("Escape");
      await expect(
        page.getByRole("button", { name: /^Filters/ }),
      ).toBeFocused();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
    await page.goto("/login");
    const email = page.getByLabel("Email address");
    await email.click();
    await keyboardReturn(page, email);
    await expect(email).toHaveCSS("outline-color", teal);
    await expect(email).toHaveCSS("outline-width", "2px");
    await page.screenshot({ path: `${evidence}/auth-${width}.png` });
  });
}

test("shared host select, textarea and file control retain visible keyboard focus", async ({
  page,
}) => {
  test.skip(
    !process.env.SEED_HOST_EMAIL || !process.env.SEED_HOST_PASSWORD,
    "Requires private isolated review credentials",
  );
  await mkdir(evidence, { recursive: true });
  await page.goto("/login");
  await page.getByLabel("Email address").fill(process.env.SEED_HOST_EMAIL!);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.SEED_HOST_PASSWORD!);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await page.goto("/host/listings");
  await page.getByRole("link", { name: "Edit", exact: true }).first().click();
  const select = page.getByLabel("Property type", { exact: true });
  await keyboardReturn(page, select);
  await expect(select).toHaveCSS("outline-color", teal);
  await expect(select).toHaveCSS("outline-width", "2px");
  await page.screenshot({ path: `${evidence}/host-select.png` });
  await page.getByRole("button", { name: /Photos & content/ }).click();
  const textarea = page.getByLabel("Description", { exact: true });
  await keyboardReturn(page, textarea);
  await expect(textarea).toHaveCSS("outline-color", teal);
  await expect(textarea).toHaveCSS("outline-width", "2px");
  const upload = page.locator('.upload-control input[type="file"]');
  await keyboardReturn(page, upload);
  await expect(page.locator(".upload-control")).toHaveCSS(
    "outline-color",
    teal,
  );
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${evidence}/host-upload.png` });
});
