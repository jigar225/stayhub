import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PublicPhotos } from "../src/discovery/PublicPhotos";
import { StayAvailability } from "../src/discovery/StayAvailability";
import type { PublicDetail } from "../src/discovery/api";
const mocks = vi.hoisted(() => ({ availability: vi.fn(), photos: vi.fn() }));
vi.mock("../src/discovery/api", () => ({ discoveryApi: mocks }));
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: new Date("2027-01-01T08:00:00Z"),
    error: "",
    refresh: vi.fn(),
  }),
}));
const listing = {
  id: "stay",
  timezone: "Europe/Lisbon",
  booking_mode: "instant",
  check_in_time: "15:00",
} as PublicDetail;
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
  mocks.availability.mockResolvedValue({
    unavailable: [{ check_in: "2027-01-15", check_out: "2027-01-17" }],
  });
});
it("opens every uploaded photo, navigates with keyboard, wraps focus and restores opener", async () => {
  render(
    <PublicPhotos
      listingId="stay"
      title="Loft"
      gallery
      photos={Array.from({ length: 7 }, (_, index) => ({
        id: String(index),
        url: `https://example.com/${index}.jpg`,
        expires_at: "2027-01-01T09:00:00Z",
        width: 800,
        height: 600,
      }))}
    />,
  );
  expect(screen.getAllByRole("img")).toHaveLength(5);
  const opener = screen.getByRole("button", { name: "Show all 7 photos" });
  await userEvent.click(opener);
  const viewer = screen.getByRole("dialog", { name: "Loft · Photos" });
  expect(within(viewer).getByRole("status")).toHaveTextContent("Photo 1 of 7");
  fireEvent.keyDown(viewer, { key: "End" });
  expect(within(viewer).getByRole("status")).toHaveTextContent("Photo 7 of 7");
  fireEvent.keyDown(viewer, { key: "ArrowRight" });
  expect(within(viewer).getByRole("status")).toHaveTextContent("Photo 1 of 7");
  const close = within(viewer).getByRole("button", {
    name: "Close photo viewer",
  });
  close.focus();
  fireEvent.keyDown(viewer, { key: "Tab", shiftKey: true });
  expect(
    within(viewer).getByRole("button", { name: "View photo 7" }),
  ).toHaveFocus();
  fireEvent(viewer, new Event("cancel", { bubbles: false, cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe("");
});
it("shows unavailable nights, permits checkout at their boundary and commits only on explicit action", async () => {
  const apply = vi.fn();
  render(
    <StayAvailability
      listing={listing}
      checkIn=""
      checkOut=""
      onApply={apply}
    />,
  );
  const unavailable = await screen.findByRole("button", {
    name: "15 Jan 2027, Unavailable night",
  });
  expect(unavailable).toBeDisabled();
  await userEvent.click(
    screen.getByRole("button", { name: "14 Jan 2027, Available night" }),
  );
  expect(unavailable).toBeEnabled();
  await userEvent.click(unavailable);
  expect(apply).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "Check these dates" }),
  );
  expect(apply).toHaveBeenCalledWith({
    check_in: "2027-01-14",
    check_out: "2027-01-15",
  });
  expect(mocks.availability).toHaveBeenCalledWith(
    "stay",
    "2027-01-01",
    "2027-02-01",
    expect.any(AbortSignal),
  );
});
it("rejects a selected range spanning an unavailable night", async () => {
  render(
    <StayAvailability
      listing={listing}
      checkIn=""
      checkOut=""
      onApply={vi.fn()}
    />,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "14 Jan 2027, Available night" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "18 Jan 2027, Available night" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "include unavailable dates",
  );
  expect(
    screen.getByRole("button", { name: "Check these dates" }),
  ).toBeDisabled();
});
it("ignores stale month data and lets a failed availability read retry", async () => {
  let finish!: (value: { unavailable: [] }) => void;
  mocks.availability
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    )
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ unavailable: [] });
  render(
    <StayAvailability
      listing={listing}
      checkIn=""
      checkOut=""
      onApply={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Next availability month" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Availability could not be loaded",
  );
  await act(async () => finish({ unavailable: [] }));
  expect(screen.getByRole("alert")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "1 Feb 2027, Available night" }),
    ).toBeEnabled(),
  );
});
