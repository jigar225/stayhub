import type { DraftFields, Listing } from "./api";
export type ListingForm = Record<keyof DraftFields, string>;
export const fieldNames: ReadonlyArray<keyof DraftFields> = [
  "property_type",
  "address",
  "destination",
  "timezone",
  "capacity",
  "bedrooms",
  "beds",
  "baths",
  "title",
  "description",
  "amenities",
  "house_rules",
  "nightly_minor",
  "cleaning_minor",
  "policy_id",
  "booking_mode",
  "check_in_time",
  "check_out_time",
];
const integers = new Set(["capacity", "bedrooms", "beds", "baths"]);
export function centsToInput(cents: number | null) {
  return cents === null
    ? ""
    : `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}
export function parseMoney(value: string): number | null {
  if (!value.trim()) return null;
  if (!/^\d+(?:[.,]\d{1,2})?$/.test(value.trim()))
    throw new Error("Enter an amount with no more than two decimal places.");
  const [whole, fraction = ""] = value.trim().replace(",", ".").split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents)) throw new Error("Enter a smaller amount.");
  return cents;
}
export function toForm(listing: Listing): ListingForm {
  return Object.fromEntries(
    fieldNames.map((key) => [
      key,
      key === "nightly_minor" || key === "cleaning_minor"
        ? centsToInput(listing[key])
        : Array.isArray(listing[key])
          ? (listing[key] as string[]).join("\n")
          : String(listing[key] ?? ""),
    ]),
  ) as ListingForm;
}
export function changedFields(
  form: ListingForm,
  baseline: Listing,
): Partial<DraftFields> {
  const changes: Record<string, unknown> = {};
  const original = toForm(baseline);
  for (const key of fieldNames) {
    if (form[key] === original[key]) continue;
    const value = form[key].trim();
    if (key === "nightly_minor" || key === "cleaning_minor")
      changes[key] = parseMoney(value);
    else if (integers.has(key)) {
      if (value && !/^\d+$/.test(value))
        throw new Error("Guest and room counts must be whole numbers.");
      changes[key] = value ? Number(value) : null;
    } else if (key === "amenities" || key === "house_rules")
      changes[key] = value
        ? Array.from(
            new Set(
              value
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean),
            ),
          )
        : [];
    else changes[key] = value || null;
  }
  return changes as Partial<DraftFields>;
}
export function formatEUR(value: number | null) {
  return value === null
    ? "Price not set"
    : new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
      }).format(value / 100);
}
