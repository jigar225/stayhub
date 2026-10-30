import { authenticated } from "../api/client";
export interface CalendarBlock {
  id: string;
  kind: "block";
  check_in: string;
  check_out: string;
}
export interface CalendarReservation {
  id: string;
  kind: "reservation";
  check_in: string;
  check_out: string;
  reservation_id: string;
  state: "pending" | "confirmed" | "checked_in" | "completed";
  code: string;
}
export type CalendarOccupancy = CalendarBlock | CalendarReservation;
export interface CalendarData {
  listing_id: string;
  timezone: string;
  start: string;
  end: string;
  items: CalendarOccupancy[];
}
export const calendarApi = {
  read: (id: string, start: string, end: string, signal?: AbortSignal) =>
    authenticated<CalendarData>(
      `/host/listings/${id}/calendar?${new URLSearchParams({ start, end })}`,
      { signal },
    ),
  block: (id: string, check_in: string, check_out: string) =>
    authenticated<{ block: CalendarBlock }>(`/host/listings/${id}/blocks`, {
      method: "POST",
      body: JSON.stringify({ check_in, check_out }),
    }),
  unblock: (id: string, block: string) =>
    authenticated<void>(`/host/listings/${id}/blocks/${block}`, {
      method: "DELETE",
    }),
};
