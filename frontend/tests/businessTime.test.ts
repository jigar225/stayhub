import { expect, it, vi } from "vitest";
it("uses server business time plus monotonic elapsed time, independent of device date", async () => {
  vi.resetModules();
  const request = vi.fn().mockResolvedValue({
    business_now: "2030-01-15T10:00:00Z",
    real_now: "2026-10-30T10:00:00Z",
  });
  vi.doMock("../src/api/client", () => ({ publicRequest: request }));
  const elapsed = vi.spyOn(performance, "now").mockReturnValue(1000);
  const clock = await import("../src/api/businessTime");
  await clock.refreshBusinessTime();
  elapsed.mockReturnValue(2500);
  expect(clock.businessNow()?.toISOString()).toBe("2030-01-15T10:00:01.500Z");
  request.mockResolvedValue({
    business_now: "2030-01-17T10:00:00Z",
    real_now: "2026-10-30T10:00:00Z",
  });
  await clock.refreshBusinessTime();
  expect(clock.businessNow()?.toISOString()).toBe("2030-01-17T10:00:00.000Z");
  elapsed.mockRestore();
  vi.doUnmock("../src/api/client");
});
