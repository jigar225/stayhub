export function dateString(date: Date) {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}
export function addDays(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return dateString(date);
}
export function validDate(value: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T12:00:00Z`)) &&
    dateString(new Date(`${value}T12:00:00Z`)) === value
  );
}
export function monthBounds(month: string) {
  const start = `${month}-01`;
  const date = new Date(`${start}T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + 1);
  return { start, end: dateString(date) };
}
export function shiftMonth(month: string, offset: number) {
  const date = new Date(`${month}-01T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + offset);
  return dateString(date).slice(0, 7);
}
export function formatDate(date: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}
export function monthLabel(month: string) {
  return new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${month}-01T12:00:00Z`));
}
export interface SearchValues {
  destination: string;
  check_in: string;
  check_out: string;
  guests: string;
}
export function searchValues(params: URLSearchParams): SearchValues {
  return {
    destination: params.get("destination") ?? "",
    check_in: params.get("check_in") ?? "",
    check_out: params.get("check_out") ?? "",
    guests: params.get("guests") ?? "1",
  };
}
export interface StaySchedule {
  timezone: string;
  booking_mode: "instant" | "request";
  check_in_time: string;
}
// Search can span timezones: only disable dates already past everywhere.
// Listing-specific eligibility remains authoritative on the business-clock API.
export function earliestCheckIn(schedule?: StaySchedule, now = new Date()) {
  if (!schedule) return dateString(new Date(now.getTime() - 12 * 3600000));
  const threshold = new Date(
    now.getTime() + (schedule.booking_mode === "request" ? 24 * 3600000 : 0),
  );
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: schedule.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(threshold);
  const part = (type: string) =>
    parts.find((value) => value.type === type)!.value;
  const day = `${part("year")}-${part("month")}-${part("day")}`;
  const localClock = `${part("hour")}:${part("minute")}:${part("second")}.${String(threshold.getUTCMilliseconds()).padStart(3, "0")}`;
  const arrivalClock = `${schedule.check_in_time.length === 5 ? `${schedule.check_in_time}:00` : schedule.check_in_time}.000`;
  const passed =
    schedule.booking_mode === "instant"
      ? arrivalClock <= localClock
      : arrivalClock < localClock;
  return passed ? addDays(day, 1) : day;
}
export function validateSearch(
  values: SearchValues,
  requireDates = false,
  minimum?: string,
) {
  const errors: Record<string, string> = {};
  if (values.destination.trim().length > 100)
    errors.destination = "Use at most 100 characters.";
  if (requireDates || values.check_in || values.check_out) {
    if (!validDate(values.check_in))
      errors.check_in = "Choose a valid check-in date.";
    if (!errors.check_in && minimum && values.check_in < minimum)
      errors.check_in = minimum
        ? "Choose a later check-in date for this listing’s local time and booking lead time."
        : "Check-in cannot be in the past. Choose a later date.";
    if (!validDate(values.check_out))
      errors.check_out = "Choose a valid check-out date.";
    if (
      !errors.check_in &&
      !errors.check_out &&
      values.check_out <= values.check_in
    )
      errors.check_out = "Check-out must be after check-in.";
  }
  if (
    !/^\d+$/.test(values.guests) ||
    Number(values.guests) < 1 ||
    Number(values.guests) > 30
  )
    errors.guests = "Choose between 1 and 30 guests.";
  return errors;
}
export function searchQuery(values: SearchValues) {
  const params = new URLSearchParams();
  if (values.destination.trim())
    params.set("destination", values.destination.trim());
  if (values.check_in) params.set("check_in", values.check_in);
  if (values.check_out) params.set("check_out", values.check_out);
  params.set("guests", values.guests);
  return params.toString();
}
