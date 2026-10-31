import { expect, type Page } from "@playwright/test";

export function dateText(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

export function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

// Navigate the actual controlled calendar rather than filling hidden fields or
// bypassing disabled-day validation. A target may be in either visible month.
export async function calendarDay(page: Page, value: string) {
  const dialog = page.getByRole("dialog", {
    name: "Choose travel dates",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  for (let turns = 0; turns < 120; turns++) {
    const day = dialog.getByRole("button", {
      name: dateLabel(value),
      exact: true,
    });
    if (await day.count()) return day;
    const first = await dialog
      .locator("[data-date]")
      .first()
      .getAttribute("data-date");
    expect(first).toBeTruthy();
    await dialog
      .getByRole("button", {
        name: value < first! ? "Previous month" : "Next month",
        exact: true,
      })
      .click();
  }
  throw new Error(`Calendar could not reach ${value}`);
}

export async function chooseDateRange(
  page: Page,
  checkIn: string,
  checkOut: string,
) {
  await page.getByRole("button", { name: "Check in", exact: true }).click();
  await (await calendarDay(page, checkIn)).click();
  await (await calendarDay(page, checkOut)).click();
  await page.getByRole("button", { name: "Apply dates", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Choose travel dates", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Check in", exact: true }),
  ).toContainText(dateText(checkIn));
  await expect(
    page.getByRole("button", { name: "Check out", exact: true }),
  ).toContainText(dateText(checkOut));
}
