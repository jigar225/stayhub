export const AMENITIES = [
  ["wifi", "Wifi"],
  ["kitchen", "Kitchen"],
  ["air-conditioning", "Air conditioning"],
  ["heating", "Heating"],
  ["washer", "Washer"],
  ["dryer", "Dryer"],
  ["workspace", "Dedicated workspace"],
  ["free-parking", "Free parking"],
  ["pool", "Pool"],
] as const;
export const FILTER_KEYS = [
  "place_group",
  "min_price_minor",
  "max_price_minor",
  "min_bedrooms",
  "min_beds",
  "amenity",
  "instant_book",
] as const;
export interface FilterDraft {
  place: string;
  minimum: string;
  maximum: string;
  bedrooms: string;
  beds: string;
  amenities: string[];
  instant: boolean;
}
export function emptyFilters(): FilterDraft {
  return {
    place: "",
    minimum: "",
    maximum: "",
    bedrooms: "0",
    beds: "0",
    amenities: [],
    instant: false,
  };
}
function euroDisplay(value: string | null) {
  if (value === null) return "";
  if (!/^\d+$/.test(value) || Number(value) > 10000000) return value;
  return `${Math.floor(Number(value) / 100)}.${value.slice(-2).padStart(2, "0")}`;
}
export function readFilters(params: URLSearchParams): FilterDraft {
  return {
    place: params.get("place_group") ?? "",
    minimum: euroDisplay(params.get("min_price_minor")),
    maximum: euroDisplay(params.get("max_price_minor")),
    bedrooms: params.get("min_bedrooms") ?? "0",
    beds: params.get("min_beds") ?? "0",
    amenities: Array.from(new Set(params.getAll("amenity"))),
    instant: params.get("instant_book") === "true",
  };
}
// Decimal strings become cents using integer arithmetic; no floating-point rounding.
export function euroCents(value: string): number | null {
  if (!value.trim()) return null;
  const match = /^(\d{1,6})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match)
    throw new Error(
      "Use a non-negative EUR amount with up to two decimal places.",
    );
  const cents =
    Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  if (cents > 10000000)
    throw new Error("Use an amount no greater than €100,000.");
  return cents;
}
export function validateFilters(draft: FilterDraft) {
  const errors: Record<string, string> = {};
  let minimum: number | null = null;
  let maximum: number | null = null;
  try {
    minimum = euroCents(draft.minimum);
  } catch (error) {
    errors.minimum = (error as Error).message;
  }
  try {
    maximum = euroCents(draft.maximum);
  } catch (error) {
    errors.maximum = (error as Error).message;
  }
  if (minimum !== null && maximum !== null && minimum > maximum)
    errors.maximum = "Maximum must be at least the minimum nightly price.";
  if (!["", "entire", "private"].includes(draft.place))
    errors.place = "Choose a supported type of place.";
  for (const [key, limit] of [
    ["bedrooms", 20],
    ["beds", 30],
  ] as const) {
    if (!/^\d+$/.test(draft[key]) || Number(draft[key]) > limit)
      errors[key] = `Choose a whole number from 0 to ${limit}.`;
  }
  if (
    draft.amenities.some((value) => !AMENITIES.some(([key]) => key === value))
  )
    errors.amenities = "Choose one of the supported amenities.";
  return errors;
}
export function applyFilters(params: URLSearchParams, draft: FilterDraft) {
  if (Object.keys(validateFilters(draft)).length)
    throw new Error("Invalid filters");
  const next = new URLSearchParams(params);
  FILTER_KEYS.forEach((key) => next.delete(key));
  next.delete("cursor");
  if (draft.place) next.set("place_group", draft.place);
  const minimum = euroCents(draft.minimum),
    maximum = euroCents(draft.maximum);
  if (minimum !== null) next.set("min_price_minor", String(minimum));
  if (maximum !== null) next.set("max_price_minor", String(maximum));
  if (Number(draft.bedrooms)) next.set("min_bedrooms", draft.bedrooms);
  if (Number(draft.beds)) next.set("min_beds", draft.beds);
  AMENITIES.forEach(([key]) => {
    if (draft.amenities.includes(key)) next.append("amenity", key);
  });
  if (draft.instant) next.set("instant_book", "true");
  return next;
}
// Each non-default group counts once; each selected amenity counts once.
// A two-sided price range is one group, not two filters.
export function activeFilterCount(params: URLSearchParams) {
  const draft = readFilters(params);
  return (
    Number(!!draft.place) +
    Number(!!draft.minimum || !!draft.maximum) +
    Number(Number(draft.bedrooms) > 0) +
    Number(Number(draft.beds) > 0) +
    draft.amenities.length +
    Number(draft.instant)
  );
}
