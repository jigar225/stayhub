import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { arrivingToday } from "../src/booking/arrivals";
import { TripPhoto } from "../src/booking/TripPhoto";
import { HostToday } from "../src/booking/HostToday";
import type { Reservation } from "../src/booking/api";
const mocks = vi.hoisted(() => ({
  photos: vi.fn(),
  today: vi.fn(),
  refresh: vi.fn(),
  now: new Date("2027-01-15T00:30:00Z") as Date | null,
  error: "",
}));
vi.mock("../src/booking/api", async (original) => ({
  ...(await original<typeof import("../src/booking/api")>()),
  bookingApi: { photos: mocks.photos, today: mocks.today },
}));
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: mocks.now,
    error: mocks.error,
    refresh: mocks.refresh,
  }),
}));
afterEach(() => vi.unstubAllGlobals());
function reservation(
  id: string,
  timezone: string,
  check_in: string,
  state = "confirmed",
) {
  return {
    id,
    timezone,
    check_in,
    state,
    check_out: "2027-01-20",
    scheduled_check_in: `${check_in}T15:00:00Z`,
    guests: 2,
    code: `SH-${id}`,
    listing_snapshot: { title: `Stay ${id}` },
  } as Reservation;
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.now = new Date("2027-01-15T00:30:00Z");
  mocks.error = "";
  mocks.photos.mockResolvedValue({
    items: [
      {
        id: "photo",
        url: "https://private.invalid/photo",
        expires_at: "2027-01-15T01:00:00Z",
        width: 800,
        height: 600,
      },
    ],
  });
});
it("identifies confirmed arrivals by each reservation's local business date", () => {
  const records = [
    reservation("lisbon", "Europe/Lisbon", "2027-01-15"),
    reservation("honolulu", "Pacific/Honolulu", "2027-01-14"),
    reservation("tomorrow", "Asia/Tokyo", "2027-01-16"),
    reservation("pending", "Europe/Lisbon", "2027-01-15", "pending"),
  ];
  expect(arrivingToday(records, mocks.now!).map((r) => r.id)).toEqual([
    "honolulu",
    "lisbon",
  ]);
});
it("surfaces loaded arrivals with local check-in time and preserves Upcoming", async () => {
  mocks.today.mockResolvedValue({
    pending: [],
    upcoming: [
      reservation("today", "Europe/Lisbon", "2027-01-15"),
      reservation("later", "Europe/Lisbon", "2027-01-18"),
    ],
    hosting: [],
    checkouts: [],
    next_cursor: "more",
  });
  render(
    <MemoryRouter>
      <HostToday />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Arriving today (1 loaded)" }),
  );
  expect(screen.getByText("Stay today")).toBeVisible();
  expect(screen.queryByText("Stay later")).toBeNull();
  expect(
    screen.getByText("Arriving today · 15:00 (Europe/Lisbon)"),
  ).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Upcoming (2 loaded)" }),
  );
  expect(screen.getByText("Stay later")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Load more reservations" }),
  ).toBeVisible();
});
it("does not invent today's date when business clock is unavailable", async () => {
  mocks.now = null;
  mocks.error = "Unavailable";
  mocks.today.mockResolvedValue({
    pending: [],
    upcoming: [],
    hosting: [],
    checkouts: [],
    next_cursor: null,
  });
  render(
    <MemoryRouter>
      <HostToday />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry arrivals date" }),
  );
  expect(mocks.refresh).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Arriving today (date unavailable)" }),
  ).toBeVisible();
});
it("loads an authorized photo and renews a broken URL only once before explicit retry", async () => {
  render(<TripPhoto reservationId="reservation" title="Booked loft" />);
  const image = await screen.findByRole("img", { name: "Booked loft" });
  expect(mocks.photos).toHaveBeenCalledWith("reservation");
  fireEvent.error(image);
  await waitFor(() => expect(mocks.photos).toHaveBeenCalledTimes(2));
  fireEvent.error(await screen.findByRole("img", { name: "Booked loft" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry stay photo" }),
  );
  await waitFor(() => expect(mocks.photos).toHaveBeenCalledTimes(3));
  expect(await screen.findByRole("img", { name: "Booked loft" })).toBeVisible();
});
it("keeps a failed photo request separate from card content and allows recovery", async () => {
  mocks.photos.mockRejectedValueOnce(new Error("Unavailable"));
  render(<TripPhoto reservationId="reservation" title="Booked loft" />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry stay photo" }),
  );
  expect(await screen.findByRole("img", { name: "Booked loft" })).toBeVisible();
});

it("waits until a card approaches the viewport before requesting private photos", async () => {
  let visible: ((entries: { isIntersecting: boolean }[]) => void) | undefined;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: typeof visible) {
        visible = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  render(<TripPhoto reservationId="offscreen" title="Later stay" />);
  expect(mocks.photos).not.toHaveBeenCalled();
  await act(async () => visible?.([{ isIntersecting: true }]));
  expect(await screen.findByRole("img", { name: "Later stay" })).toBeVisible();
});
it("limits a visible batch of trip-photo requests to two in flight", async () => {
  const finish: (() => void)[] = [];
  mocks.photos.mockImplementation(
    () => new Promise((resolve) => finish.push(() => resolve({ items: [] }))),
  );
  render(
    <>
      {["a", "b", "c", "d"].map((id) => (
        <TripPhoto key={id} reservationId={id} title={id} />
      ))}
    </>,
  );
  await waitFor(() => expect(mocks.photos).toHaveBeenCalledTimes(2));
  await act(async () => finish[0]());
  await waitFor(() => expect(mocks.photos).toHaveBeenCalledTimes(3));
  await act(async () => finish[1]());
  await waitFor(() => expect(mocks.photos).toHaveBeenCalledTimes(4));
  await act(async () => {
    finish[2]();
    finish[3]();
  });
  expect(await screen.findAllByText("No stay photo available.")).toHaveLength(
    4,
  );
});
