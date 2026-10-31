import { describe, expect, it } from "vitest";
import { calendarWindow } from "../src/calendar/calendarWindow";
import { addDays } from "../src/discovery/dates";

describe("host calendar business-clock boundaries", () => {
  const now = new Date("2026-11-06T05:31:00Z");
  it("opens the business month after a demo clock advance", () => {
    expect(calendarWindow(now, "Asia/Calcutta", null).month).toBe("2026-11");
  });
  it("clips the first allowed month without requesting forbidden early days", () => {
    const value = calendarWindow(now, "Asia/Calcutta", "2026-10");
    expect(value.start).toBe("2026-10-06");
    expect(value.end).toBe("2026-11-01");
    expect(value.firstMonth).toBe("2026-10");
  });
  it("clamps stale URLs and the final month to the server limit", () => {
    expect(calendarWindow(now, "UTC", "2020-01").month).toBe("2026-10");
    expect(calendarWindow(now, "UTC", "2099-01").end).toBe(
      addDays("2026-11-06", 730),
    );
  });
  it("uses the listing timezone at a month boundary", () => {
    const time = new Date("2026-11-01T00:30:00Z");
    expect(calendarWindow(time, "America/Los_Angeles", null).month).toBe(
      "2026-10",
    );
    expect(calendarWindow(time, "Asia/Kolkata", null).month).toBe("2026-11");
  });
});
