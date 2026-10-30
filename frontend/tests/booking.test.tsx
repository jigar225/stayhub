import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, Link } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { Checkout } from "../src/booking/Checkout";
import { HostToday } from "../src/booking/HostToday";
import { TripDetail, Trips } from "../src/booking/Trips";
import { MonthGrid } from "../src/calendar/MonthGrid";
import { ApiError } from "../src/api/client";
import {
  readSubmission,
  recoveryKey,
  saveSubmission,
} from "../src/booking/recovery";
const mocks = vi.hoisted(() => ({
  pay: vi.fn(),
  detail: vi.fn(),
  quote: vi.fn(),
  trips: vi.fn(),
  reservation: vi.fn(),
  photos: vi.fn(),
  today: vi.fn(),
  decide: vi.fn(),
  user: {
    id: "guest",
    roles: ["guest"],
    name: "Guest",
    email: "guest@test.invalid",
  },
}));
vi.mock("../src/auth/useSession", () => ({
  useSession: () => ({ user: mocks.user, ready: true, error: null }),
}));
vi.mock("../src/discovery/api", async (original) => ({
  ...(await original<typeof import("../src/discovery/api")>()),
  discoveryApi: { detail: mocks.detail, quote: mocks.quote },
}));
vi.mock("../src/booking/api", async (original) => ({
  ...(await original<typeof import("../src/booking/api")>()),
  bookingApi: {
    pay: mocks.pay,
    trips: mocks.trips,
    detail: mocks.reservation,
    photos: mocks.photos,
    today: mocks.today,
    decide: mocks.decide,
  },
}));
const price = {
  nights: 5,
  nightly_minor: 12800,
  nights_minor: 64000,
  cleaning_minor: 3500,
  subtotal_minor: 67500,
  guest_fee_minor: 9450,
  total_minor: 76950,
  currency: "EUR",
};
const policy = {
  id: "policy",
  name: "Moderate",
  version: 1,
  terms: "Booked policy terms",
  definition: { cutoff_days: 5 },
};
const listing = {
  id: "listing",
  title: "Snapshot loft",
  destination: "Lisbon",
  property_type: "apartment",
  description: "Booked description",
  house_rules: ["Quiet after 11"],
  amenities: ["Wifi"],
  host_name: "Host",
  timezone: "Europe/Lisbon",
  booking_mode: "request",
  photos: [],
  check_in_time: "15:00",
  check_out_time: "11:00",
};
const quote = {
  ...price,
  listing_id: "listing",
  check_in: "2027-01-15",
  check_out: "2027-01-20",
  guests: 2,
  booking_mode: "request",
  policy,
  scheduled_check_in: "2027-01-15T15:00:00Z",
  scheduled_check_out: "2027-01-20T11:00:00Z",
  expires_at: "2027-01-01T10:10:00Z",
  quote_token: "original-reviewed-token",
};
const reservation = {
  id: "reservation",
  code: "SH-TEST123",
  guest_id: "guest",
  host_id: "host",
  state: "pending",
  reason: null,
  ...quote,
  listing_snapshot: listing,
  price,
  payment: {
    id: "payment",
    amount_minor: 76950,
    currency: "EUR",
    paid_at: "2027-01-01T10:00:00Z",
  },
  refund: null,
  request_deadline: "2027-01-02T10:00:00Z",
  timezone: "Europe/Lisbon",
  host_fee_minor: 2025,
  host_entitlement_minor: 65475,
  platform_entitlement_minor: 11475,
};
const path =
  "/checkout/listing?check_in=2027-01-15&check_out=2027-01-20&guests=2";
function checkout() {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="checkout/:listingId"
          element={
            <>
              <Link to="/checkout/listing?check_in=2027-02-15&check_out=2027-02-20&guests=2">
                Change dates
              </Link>
              <Checkout />
            </>
          }
        />
        <Route path="trips/:id" element={<p>Successful reservation</p>} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mocks.user = {
    id: "guest",
    roles: ["guest"],
    name: "Guest",
    email: "guest@test.invalid",
  };
  mocks.detail.mockResolvedValue({ listing });
  mocks.quote.mockResolvedValue({ quote });
  mocks.photos.mockResolvedValue({ items: [] });
  mocks.reservation.mockResolvedValue({ reservation });
  mocks.pay.mockResolvedValue({ reservation });
  mocks.today.mockResolvedValue({
    pending: [reservation],
    upcoming: [],
    hosting: [],
    checkouts: [],
    next_cursor: null,
  });
});
it("retains original Pay key/payload after unknown outcome and reload, with no fresh quote", async () => {
  mocks.pay.mockRejectedValueOnce(new Error("Network interrupted"));
  const first = checkout();
  await userEvent.click(
    await screen.findByRole("button", { name: "Pay €769.50" }),
  );
  expect(
    await screen.findByText(/payment outcome is unresolved/),
  ).toBeVisible();
  const sent = mocks.pay.mock.calls[0];
  expect(sessionStorage.getItem(recoveryKey)).toContain(sent[0]);
  first.unmount();
  mocks.quote.mockClear();
  checkout();
  expect(
    await screen.findByRole("button", { name: "Retry original payment" }),
  ).toBeVisible();
  expect(mocks.quote).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "Retry original payment" }),
  );
  expect(await screen.findByText("Successful reservation")).toBeVisible();
  expect(mocks.pay.mock.calls[1]).toEqual(sent);
  expect(sessionStorage.getItem(recoveryKey)).toBeNull();
});
it("disables duplicate Pay and requires explicit fresh review after a stale quote", async () => {
  let reject!: (reason: unknown) => void;
  mocks.pay.mockImplementationOnce(
    () =>
      new Promise((_resolve, no) => {
        reject = no;
      }),
  );
  checkout();
  await userEvent.click(
    await screen.findByRole("button", { name: "Pay €769.50" }),
  );
  expect(
    screen.getByRole("button", { name: "Resolving payment…" }),
  ).toBeDisabled();
  expect(mocks.pay).toHaveBeenCalledTimes(1);
  await act(async () =>
    reject(
      new ApiError(409, {
        code: "stale_quote",
        message: "Price changed",
        field_errors: null,
        request_id: "test",
      }),
    ),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Price changed");
  expect(mocks.quote).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(recoveryKey)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("button", { name: "Pay €769.50" });
  expect(mocks.quote).toHaveBeenCalledTimes(2);
});
it("never offers an old quote while changed route dates are loading", async () => {
  checkout();
  await screen.findByRole("button", { name: "Pay €769.50" });
  mocks.quote.mockReturnValueOnce(new Promise(() => {}));
  await userEvent.click(screen.getByRole("link", { name: "Change dates" }));
  expect(screen.queryByRole("button", { name: /Pay €/ })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Loading your current price",
  );
});
it("clears recovery for a positively different actor but keeps same-actor recovery", () => {
  saveSubmission({
    actor: "guest",
    listing: "listing",
    check_in: "2027-01-15",
    check_out: "2027-01-20",
    guests: 2,
    token: "signed-quote",
    key: "original-key",
  });
  expect(readSubmission("guest")?.key).toBe("original-key");
  expect(readSubmission("other-guest")).toBeNull();
  expect(sessionStorage.getItem(recoveryKey)).toBeNull();
});
it("requires decline reason, retains original uncertain decision and uses server update", async () => {
  mocks.decide.mockRejectedValueOnce(new Error("Unknown decision outcome"));
  render(
    <MemoryRouter>
      <HostToday />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Decline request" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm decline" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("1–500");
  expect(mocks.decide).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Decline reason"), {
    target: { value: "Not available" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm decline" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original decision" }),
  );
  await waitFor(() => expect(mocks.decide).toHaveBeenCalledTimes(2));
  expect(mocks.decide.mock.calls[1]).toEqual(mocks.decide.mock.calls[0]);
});
it("loads real trip pagination and booked snapshot/payment after unlisting", async () => {
  mocks.trips
    .mockResolvedValueOnce({ items: [], next_cursor: "more" })
    .mockResolvedValueOnce({ items: [reservation], next_cursor: null });
  const list = render(
    <MemoryRouter>
      <Trips />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Load more trips" }),
  );
  expect(await screen.findByText("SH-TEST123")).toBeVisible();
  expect(mocks.trips.mock.calls[1]).toEqual(["upcoming", "more"]);
  list.unmount();
  render(
    <MemoryRouter initialEntries={["/trips/reservation"]}>
      <Routes>
        <Route path="trips/:id" element={<TripDetail />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText("Booked description")).toBeVisible();
  expect(screen.getByText("Booked policy terms")).toBeVisible();
  expect(screen.getByText("Simulated charge:")).toBeVisible();
  expect(mocks.photos).toHaveBeenCalledWith("reservation");
});
it("distinguishes reservation calendar occupancy from removable host blocks", () => {
  const select = vi.fn();
  render(
    <MonthGrid
      month="2027-01"
      blocks={[
        {
          id: "entry",
          kind: "reservation",
          reservation_id: "reservation",
          state: "pending",
          code: "SH-TEST123",
          check_in: "2027-01-15",
          check_out: "2027-01-17",
        },
      ]}
      onSelect={select}
      selectedStart=""
      selectedEnd=""
    />,
  );
  expect(
    screen.getByRole("button", { name: "15 Jan 2027, Pending" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "17 Jan 2027, Available" }),
  ).toBeVisible();
});

it("keeps recovery when Pay finishes after navigating away, then resolves on remount", async () => {
  let finish!: (value: { reservation: typeof reservation }) => void;
  mocks.pay.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const first = checkout();
  await userEvent.click(
    await screen.findByRole("button", { name: "Pay €769.50" }),
  );
  const original = mocks.pay.mock.calls[0];
  first.unmount();
  await act(async () => finish({ reservation }));
  expect(sessionStorage.getItem(recoveryKey)).not.toBeNull();
  checkout();
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original payment" }),
  );
  expect(await screen.findByText("Successful reservation")).toBeVisible();
  expect(mocks.pay.mock.calls[1]).toEqual(original);
});

for (const failure of [false, true]) {
  it(`Trips ignores stale pagination ${failure ? "failure" : "success"} after category A → B → A`, async () => {
    let resolve!: (value: {
      items: (typeof reservation)[];
      next_cursor: null;
    }) => void;
    let reject!: (error: Error) => void;
    const old = new Promise<{
      items: (typeof reservation)[];
      next_cursor: null;
    }>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    mocks.trips
      .mockResolvedValueOnce({ items: [reservation], next_cursor: "old" })
      .mockReturnValueOnce(old)
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockResolvedValueOnce({
        items: [{ ...reservation, code: "CURRENT-TRIP" }],
        next_cursor: "current",
      });
    render(
      <MemoryRouter>
        <Trips />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more trips" }),
    );
    await userEvent.click(screen.getByRole("button", { name: /^Past$/ }));
    await screen.findByText("No trips in this category");
    await userEvent.click(screen.getByRole("button", { name: /^Upcoming$/ }));
    await screen.findByText("CURRENT-TRIP");
    await act(async () => {
      if (failure) reject(new Error("obsolete trips error"));
      else
        resolve({
          items: [{ ...reservation, code: "OBSOLETE-TRIP" }],
          next_cursor: null,
        });
    });
    expect(screen.getByText("CURRENT-TRIP")).toBeVisible();
    expect(screen.queryByText("OBSOLETE-TRIP")).toBeNull();
    expect(screen.queryByText("obsolete trips error")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Load more trips" }),
    ).toBeEnabled();
    mocks.trips.mockResolvedValueOnce({ items: [], next_cursor: null });
    await userEvent.click(
      screen.getByRole("button", { name: "Load more trips" }),
    );
    expect(mocks.trips.mock.calls.at(-1)).toEqual(["upcoming", "current"]);
  });
  it(`Today ignores stale pagination ${failure ? "failure" : "success"} after a host decision refresh`, async () => {
    let resolve!: (value: {
      pending: (typeof reservation)[];
      upcoming: (typeof reservation)[];
      hosting: never[];
      checkouts: never[];
      next_cursor: null;
    }) => void;
    let reject!: (error: Error) => void;
    const old = new Promise<{
      pending: (typeof reservation)[];
      upcoming: (typeof reservation)[];
      hosting: never[];
      checkouts: never[];
      next_cursor: null;
    }>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    mocks.today
      .mockResolvedValueOnce({
        pending: [{ ...reservation, state: "pending" }],
        upcoming: [],
        hosting: [],
        checkouts: [],
        next_cursor: "old",
      })
      .mockReturnValueOnce(old)
      .mockResolvedValueOnce({
        pending: [],
        upcoming: [{ ...reservation, state: "confirmed" }],
        hosting: [],
        checkouts: [],
        next_cursor: "current",
      });
    mocks.decide.mockResolvedValue({
      reservation: { ...reservation, state: "confirmed" },
    });
    render(
      <MemoryRouter>
        <HostToday />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more reservations" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Accept request" }),
    );
    await screen.findByText("No pending requests");
    await act(async () => {
      if (failure) reject(new Error("obsolete today error"));
      else
        resolve({
          pending: [{ ...reservation, code: "OBSOLETE-REQUEST" }],
          upcoming: [],
          hosting: [],
          checkouts: [],
          next_cursor: null,
        });
    });
    expect(screen.getByText("No pending requests")).toBeVisible();
    expect(screen.queryByText("OBSOLETE-REQUEST")).toBeNull();
    expect(screen.queryByText("obsolete today error")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Load more reservations" }),
    ).toBeEnabled();
    mocks.today.mockResolvedValueOnce({
      pending: [],
      upcoming: [],
      hosting: [],
      checkouts: [],
      next_cursor: null,
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Load more reservations" }),
    );
    expect(mocks.today.mock.calls.at(-1)).toEqual(["current"]);
  });
}
