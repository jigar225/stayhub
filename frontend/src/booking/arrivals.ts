import type { Reservation } from "./api";

/** Presentation only: the server still owns reservation lifecycle and eligibility. */
export function arrivingToday(
  reservations: Reservation[],
  now: Date,
): Reservation[] {
  return reservations
    .filter((reservation) => {
      if (reservation.state !== "confirmed") return false;
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: reservation.timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(now);
      const value = (type: string) =>
        parts.find((part) => part.type === type)?.value;
      return (
        reservation.check_in ===
        `${value("year")}-${value("month")}-${value("day")}`
      );
    })
    .sort((left, right) =>
      left.scheduled_check_in.localeCompare(right.scheduled_check_in),
    );
}
export function arrivalTime(reservation: Reservation): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: reservation.timezone,
  }).format(new Date(reservation.scheduled_check_in));
}
