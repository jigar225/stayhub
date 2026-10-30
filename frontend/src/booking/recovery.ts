import { validDate } from "../discovery/dates";
export const recoveryKey = "stayhub-pay-submission-v1";
export interface PaySubmission {
  actor: string;
  listing: string;
  check_in: string;
  check_out: string;
  guests: number;
  token: string;
  key: string;
}
export function clearSubmission() {
  try {
    sessionStorage.removeItem(recoveryKey);
  } catch {
    /* Storage may be unavailable; Pay will remain disabled by save failure. */
  }
}
export function readSubmission(actor: string): PaySubmission | null {
  try {
    const raw = sessionStorage.getItem(recoveryKey);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") throw new Error();
    const item = value as PaySubmission;
    if (
      item.actor !== actor ||
      ![
        item.listing,
        item.check_in,
        item.check_out,
        item.token,
        item.key,
      ].every((value) => typeof value === "string" && value.length > 0) ||
      !Number.isInteger(item.guests) ||
      item.guests < 1 ||
      item.guests > 30 ||
      !validDate(item.check_in) ||
      !validDate(item.check_out) ||
      item.check_out <= item.check_in
    )
      throw new Error();
    return item;
  } catch {
    clearSubmission();
    return null;
  }
}
export function saveSubmission(value: PaySubmission) {
  sessionStorage.setItem(recoveryKey, JSON.stringify(value));
}
