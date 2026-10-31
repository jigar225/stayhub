import { addDays, monthBounds, validDate } from "../discovery/dates";

export function calendarWindow(
  now: Date,
  timezone: string,
  requested: string | null,
) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) =>
    parts.find((item) => item.type === type)!.value;
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  const min = addDays(today, -31);
  const max = addDays(today, 730); // Exclusive API range boundary.
  const firstMonth = min.slice(0, 7);
  const lastMonth = addDays(max, -1).slice(0, 7);
  const valid =
    requested &&
    /^\d{4}-\d{2}$/.test(requested) &&
    validDate(`${requested}-01`);
  const desired = valid ? requested : today.slice(0, 7);
  const month =
    desired < firstMonth
      ? firstMonth
      : desired > lastMonth
        ? lastMonth
        : desired;
  const bounds = monthBounds(month);
  return {
    today,
    month,
    firstMonth,
    lastMonth,
    start: bounds.start < min ? min : bounds.start,
    end: bounds.end > max ? max : bounds.end,
  };
}
