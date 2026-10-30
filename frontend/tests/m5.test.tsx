import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { Cancellation, CancellationActions } from "../src/booking/Cancellation";
import { Earnings } from "../src/booking/Earnings";
import { AdminPage } from "../src/pages/AdminPage";
import { ApiError } from "../src/api/client";
import { HostToday } from "../src/booking/HostToday";
const m = vi.hoisted(() => ({
  detail: vi.fn(),
  preview: vi.fn(),
  cancel: vi.fn(),
  hostCancel: vi.fn(),
  earnings: vi.fn(),
  today: vi.fn(),
  events: vi.fn(),
  clock: vi.fn(),
  advance: vi.fn(),
  sweep: vi.fn(),
  refresh: vi.fn(),
  now: new Date("2027-01-01T10:00:00Z"),
  user: { id: "guest", roles: ["guest"] },
}));
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({ now: m.now, error: "", refresh: m.refresh }),
  refreshBusinessTime: m.refresh,
}));
vi.mock("../src/auth/useSession", () => ({
  useSession: () => ({ user: m.user }),
}));
vi.mock("../src/booking/api", async (original) => ({
  ...(await original<typeof import("../src/booking/api")>()),
  bookingApi: {
    detail: m.detail,
    cancellationPreview: m.preview,
    cancel: m.cancel,
    hostCancel: m.hostCancel,
    earnings: m.earnings,
    today: m.today,
  },
}));
vi.mock("../src/admin/api", () => ({
  adminApi: {
    events: m.events,
    clock: m.clock,
    advance: m.advance,
    sweep: m.sweep,
  },
}));
const reservation = {
  id: "r",
  code: "SH-TEST",
  guest_id: "guest",
  host_id: "host",
  listing_id: "listing",
  state: "confirmed" as const,
  reason: null,
  booking_mode: "instant" as const,
  check_in: "2027-01-15",
  check_out: "2027-01-20",
  guests: 2,
  timezone: "Europe/Lisbon",
  scheduled_check_in: "2027-01-15T15:00:00Z",
  scheduled_check_out: "2027-01-20T11:00:00Z",
  created_at: "2027-01-01T10:00:00Z",
  request_deadline: null,
  listing_snapshot: {
    title: "Booked loft",
    destination: "Lisbon",
    property_type: "apartment",
    description: "Booked description",
    amenities: [],
    house_rules: [],
    host_name: "Host",
  },
  policy: {
    id: "policy",
    name: "Moderate",
    version: 1,
    terms: "Booked terms",
    definition: {},
  },
  price: {
    nights: 5,
    nightly_minor: 12800,
    nights_minor: 64000,
    cleaning_minor: 3500,
    subtotal_minor: 67500,
    guest_fee_minor: 9450,
    total_minor: 76950,
    currency: "EUR" as const,
  },
  host_fee_minor: 2025,
  host_entitlement_minor: 65475,
  platform_entitlement_minor: 11475,
  payment: {
    id: "payment",
    amount_minor: 76950,
    currency: "EUR" as const,
    paid_at: "2027-01-01T10:00:00Z",
  },
  refund: null,
};
const preview = {
  reservation_id: "r",
  state: "confirmed",
  financial_version: 1,
  policy_name: "Moderate",
  policy_version: 1,
  refund_percent: 50,
  nights_refund_minor: 32000,
  cleaning_refund_minor: 3500,
  guest_fee_refund_minor: 4725,
  total_refund_minor: 40225,
  explanation: "50% of nights and the original guest fee; cleaning in full.",
  expires_at: "2027-01-01T10:05:00Z",
  confirmation_token: "reviewed-token",
};
const clock = {
  business_now: "2027-01-01T10:00:00Z",
  real_now: "2026-10-30T10:00:00Z",
  offset_seconds: 1000,
  version: 2,
  demo_mode: true,
};
const sweep = {
  scanned: 1,
  expired: 0,
  checked_in: 1,
  completed: 1,
  paid: 1,
  deferred: 0,
  has_more: false,
};
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  m.user = { id: "guest", roles: ["guest"] };
  m.now = new Date("2027-01-01T10:00:00Z");
  m.detail.mockResolvedValue({ reservation });
  m.preview.mockResolvedValue({ preview });
  m.events.mockResolvedValue({ items: [], next_cursor: null });
  m.clock.mockResolvedValue(clock);
  m.advance.mockResolvedValue({ clock, sweep });
  m.sweep.mockResolvedValue({ sweep });
});
function cancelPage() {
  render(
    <MemoryRouter initialEntries={["/trips/r/cancel"]}>
      <Routes>
        <Route path="trips/:id/cancel" element={<Cancellation />} />
        <Route path="trips/:id" element={<p>Cancelled reservation detail</p>} />
      </Routes>
    </MemoryRouter>,
  );
}
it("reviews exact refund components and requires a new preview after stale rejection", async () => {
  m.cancel.mockRejectedValueOnce(
    new ApiError(409, {
      code: "stale_cancellation",
      message: "Refund window changed",
      field_errors: null,
      request_id: "test",
    }),
  );
  cancelPage();
  await screen.findByText("€402.25");
  expect(screen.getByText("€320.00")).toBeVisible();
  expect(screen.getByText("€35.00")).toBeVisible();
  expect(screen.getByText("€47.25")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Cancel reservation" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Refund window changed",
  );
  expect(m.preview).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: "Cancel reservation" }),
  ).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("button", { name: "Cancel reservation" });
  expect(m.preview).toHaveBeenCalledTimes(2);
});
it("retries uncertain cancellation with the original confirmation token/key", async () => {
  m.cancel
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce({ reservation });
  cancelPage();
  await userEvent.click(
    await screen.findByRole("button", { name: "Cancel reservation" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original cancellation" }),
  );
  expect(await screen.findByText("Cancelled reservation detail")).toBeVisible();
  expect(m.cancel.mock.calls[1]).toEqual(m.cancel.mock.calls[0]);
});
it("explains cleaning-only refunds at zero percent", async () => {
  m.preview.mockResolvedValue({
    preview: {
      ...preview,
      refund_percent: 0,
      nights_refund_minor: 0,
      guest_fee_refund_minor: 0,
      total_refund_minor: 3500,
    },
  });
  cancelPage();
  expect(
    await screen.findByText("0% refund on nights and guest service fee"),
  ).toBeVisible();
  expect(
    screen.getByText(/including when the nights refund is 0%/),
  ).toBeVisible();
  expect(screen.getAllByText("€35.00")).toHaveLength(2);
});
it("host cancellation requires a reason, then confirms full refund and blocks at check-in", async () => {
  m.user = { id: "host", roles: ["host"] };
  const update = vi.fn();
  m.hostCancel.mockResolvedValue({ reservation });
  const view = render(
    <MemoryRouter>
      <CancellationActions reservation={reservation} onUpdated={update} />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Cancel as host" }));
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm host cancellation" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("1–500");
  expect(m.hostCancel).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Cancellation reason"), {
    target: { value: "Emergency maintenance" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm host cancellation" }),
  );
  expect(m.hostCancel.mock.calls[0].slice(0, 2)).toEqual([
    "r",
    "Emergency maintenance",
  ]);
  expect(update).toHaveBeenCalled();
  m.now = new Date(reservation.scheduled_check_in);
  view.rerender(
    <MemoryRouter>
      <CancellationActions reservation={reservation} onUpdated={update} />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("button", { name: "Cancel as host" })).toBeNull();
});
it("earnings displays server-wide totals while paginating retained cancellation rows", async () => {
  const payout = {
    id: "p",
    reservation_id: "r",
    code: "SH-TEST",
    listing_title: "Booked loft",
    host_id: "host",
    due_at: "2027-01-16T15:00:00Z",
    gross_minor: 32000,
    host_fee_minor: 960,
    net_minor: 31040,
    status: "scheduled",
    paid_at: null,
    retained_cancellation: true,
  };
  m.earnings
    .mockResolvedValueOnce({
      totals: { paid_minor: 65475, upcoming_minor: 31040, held_minor: 12000 },
      items: [],
      next_cursor: "next",
    })
    .mockResolvedValueOnce({
      totals: { paid_minor: 65475, upcoming_minor: 31040, held_minor: 12000 },
      items: [payout],
      next_cursor: null,
    });
  render(
    <MemoryRouter>
      <Earnings />
    </MemoryRouter>,
  );
  expect(await screen.findByText("€654.75")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Load more earnings" }),
  );
  expect(
    await screen.findByText("Retained cancellation earnings"),
  ).toBeVisible();
  expect(m.earnings.mock.calls[1]).toEqual(["", "next"]);
});
it("admin requires explicit global advance confirmation and retries identical unknown advance", async () => {
  m.advance
    .mockRejectedValueOnce(new Error("Unknown advance outcome"))
    .mockResolvedValueOnce({ clock, sweep });
  render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  );
  await screen.findByRole("button", { name: "Review clock advance" });
  fireEvent.change(screen.getByLabelText("Advance by seconds"), {
    target: { value: "172800" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Review clock advance" }),
  );
  expect(m.advance).not.toHaveBeenCalled();
  expect(screen.getByText(/affects every booking/)).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm global advance" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original clock advance" }),
  );
  await waitFor(() => expect(m.advance).toHaveBeenCalledTimes(2));
  expect(m.advance.mock.calls[1]).toEqual(m.advance.mock.calls[0]);
  expect(await screen.findByText(/completed 1 · paid 1/)).toBeVisible();
});
it("Today uses actual lifecycle arrays and labels loaded counts", async () => {
  m.today.mockResolvedValue({
    pending: [],
    upcoming: [],
    hosting: [{ ...reservation, state: "checked_in" }],
    checkouts: [
      {
        ...reservation,
        id: "completed",
        code: "SH-COMPLETE",
        state: "completed",
      },
    ],
    next_cursor: null,
  });
  render(
    <MemoryRouter>
      <HostToday />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Currently hosting (1 loaded)" }),
  );
  expect(screen.getByText("Checked in")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Checking out (1 loaded)" }),
  );
  expect(screen.getByText("Completed")).toBeVisible();
});
it("resolves the same global clock advance after an unknown outcome and remount", async () => {
  m.advance
    .mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValueOnce({ clock, sweep });
  const first = render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Review clock advance" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm global advance" }),
  );
  await screen.findByRole("button", { name: "Retry original clock advance" });
  const original = m.advance.mock.calls[0];
  first.unmount();
  render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original clock advance" }),
  );
  await waitFor(() => expect(m.advance).toHaveBeenCalledTimes(2));
  expect(m.advance.mock.calls[1]).toEqual(original);
  expect(screen.getByLabelText("Advance by seconds")).toBeVisible();
});
it("recovers original cancellation after reload without requesting another preview", async () => {
  m.cancel
    .mockRejectedValueOnce(new Error("Lost cancellation response"))
    .mockResolvedValueOnce({ reservation });
  const first = render(
    <MemoryRouter initialEntries={["/trips/r/cancel"]}>
      <Routes>
        <Route path="trips/:id/cancel" element={<Cancellation />} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Cancel reservation" }),
  );
  await screen.findByRole("button", { name: "Retry original cancellation" });
  const original = m.cancel.mock.calls[0];
  first.unmount();
  m.preview.mockClear();
  cancelPage();
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry original cancellation" }),
  );
  expect(await screen.findByText("Cancelled reservation detail")).toBeVisible();
  expect(m.preview).not.toHaveBeenCalled();
  expect(m.cancel.mock.calls[1]).toEqual(original);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const earningsPage = (label: string, cursor: string | null = "next") => ({
  totals: {
    paid_minor: label === "current" ? 12345 : 99999,
    upcoming_minor: 0,
    held_minor: 0,
  },
  items: [
    {
      id: label,
      reservation_id: label,
      code: label,
      listing_title: label,
      host_id: "host",
      due_at: "2027-01-01T00:00:00Z",
      gross_minor: 100,
      host_fee_minor: 3,
      net_minor: 97,
      status: "paid",
      paid_at: null,
      retained_cancellation: false,
    },
  ],
  next_cursor: cursor,
});
const eventsPage = (label: string, cursor: string | null = "next") => ({
  items: [
    {
      id: label,
      action: label,
      target_type: "reservation",
      target_id: label,
      actor_id: null,
      system_identity: "system",
      before: null,
      after: {},
      business_at: "2027-01-01T00:00:00Z",
      recorded_at: "2027-01-01T00:00:00Z",
    },
  ],
  next_cursor: cursor,
});
for (const failure of [false, true]) {
  it(`earnings ignores obsolete pagination ${failure ? "failure" : "success"} across A → B → A and keeps current loading/retry`, async () => {
    const old = deferred<ReturnType<typeof earningsPage>>();
    const current = deferred<ReturnType<typeof earningsPage>>();
    m.earnings
      .mockResolvedValueOnce(earningsPage("initial"))
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(earningsPage("other"))
      .mockResolvedValueOnce(earningsPage("current"))
      .mockReturnValueOnce(current.promise);
    render(
      <MemoryRouter>
        <Earnings />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more earnings" }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Payout status"),
      "paid",
    );
    await screen.findByRole("link", { name: "other" });
    await userEvent.selectOptions(screen.getByLabelText("Payout status"), "");
    await screen.findByText("€123.45");
    await act(async () => {
      if (failure) old.reject(new Error("obsolete error"));
      else old.resolve(earningsPage("obsolete", null));
    });
    expect(screen.getByText("€123.45")).toBeVisible();
    expect(screen.queryByText("obsolete")).toBeNull();
    expect(screen.queryByText("obsolete error")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Load more earnings" }),
    );
    expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled();
    await act(async () => current.reject(new Error("current error")));
    expect(await screen.findByRole("alert")).toHaveTextContent("current error");
    m.earnings.mockResolvedValueOnce(earningsPage("recovered", null));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("link", { name: "recovered" }),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(m.earnings.mock.calls.at(-1)).toEqual(["", "next"]);
  });
  it(`admin ignores obsolete pagination ${failure ? "failure" : "success"} after filter and same-filter refresh`, async () => {
    const old = deferred<ReturnType<typeof eventsPage>>();
    const current = deferred<ReturnType<typeof eventsPage>>();
    m.events
      .mockResolvedValueOnce(eventsPage("initial"))
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(eventsPage("filtered"))
      .mockResolvedValueOnce(eventsPage("current"))
      .mockReturnValueOnce(current.promise);
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more events" }),
    );
    fireEvent.change(screen.getByLabelText("Action"), {
      target: { value: "paid" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Filter events" }),
    );
    await screen.findByRole("cell", { name: /filtered/ });
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh events" }),
    );
    await screen.findByRole("cell", { name: /current/ });
    await act(async () => {
      if (failure) old.reject(new Error("obsolete error"));
      else old.resolve(eventsPage("obsolete", null));
    });
    expect(screen.getByRole("cell", { name: /current/ })).toBeVisible();
    expect(screen.queryByText("obsolete error")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Load more events" }),
    );
    expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled();
    await act(async () => current.reject(new Error("current event error")));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "current event error",
    );
    m.events.mockResolvedValueOnce(eventsPage("recovered", null));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("cell", { name: /recovered/ }),
    ).toBeVisible();
    expect(m.events.mock.calls.at(-1)).toEqual(["paid", "", "next"]);
  });
  it(`unmounted views ignore late pagination ${failure ? "failures" : "successes"}`, async () => {
    const oldE = deferred<ReturnType<typeof earningsPage>>();
    const oldA = deferred<ReturnType<typeof eventsPage>>();
    m.earnings
      .mockResolvedValueOnce(earningsPage("initial"))
      .mockReturnValueOnce(oldE.promise);
    m.events
      .mockResolvedValueOnce(eventsPage("initial event"))
      .mockReturnValueOnce(oldA.promise);
    const first = render(
      <MemoryRouter>
        <Earnings />
        <AdminPage />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more earnings" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more events" }),
    );
    first.unmount();
    m.earnings.mockResolvedValueOnce(earningsPage("current", null));
    m.events.mockResolvedValueOnce(eventsPage("current event", null));
    render(
      <MemoryRouter>
        <Earnings />
        <AdminPage />
      </MemoryRouter>,
    );
    await screen.findByText("€123.45");
    await screen.findByRole("cell", { name: /current event/ });
    await act(async () => {
      if (failure) {
        oldE.reject(new Error("obsolete earnings"));
        oldA.reject(new Error("obsolete events"));
      } else {
        oldE.resolve(earningsPage("obsolete", null));
        oldA.resolve(eventsPage("obsolete", null));
      }
    });
    expect(screen.getByText("€123.45")).toBeVisible();
    expect(screen.getByRole("cell", { name: /current event/ })).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
}

for (const failure of [false, true]) {
  it(`obsolete pagination ${failure ? "errors" : "successes"} preserve newer request errors on both screens`, async () => {
    const oldE = deferred<ReturnType<typeof earningsPage>>();
    const oldA = deferred<ReturnType<typeof eventsPage>>();
    m.earnings
      .mockResolvedValueOnce(earningsPage("initial"))
      .mockReturnValueOnce(oldE.promise)
      .mockRejectedValueOnce(new Error("current earnings error"));
    m.events
      .mockResolvedValueOnce(eventsPage("initial event"))
      .mockReturnValueOnce(oldA.promise)
      .mockRejectedValueOnce(new Error("current events error"));
    render(
      <MemoryRouter>
        <Earnings />
        <AdminPage />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more earnings" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more events" }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Payout status"),
      "paid",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh events" }),
    );
    await screen.findByText("current earnings error");
    await screen.findByText("current events error");
    await act(async () => {
      if (failure) {
        oldE.reject(new Error("obsolete earnings"));
        oldA.reject(new Error("obsolete events"));
      } else {
        oldE.resolve(earningsPage("obsolete", null));
        oldA.resolve(eventsPage("obsolete", null));
      }
    });
    expect(screen.getByText("current earnings error")).toBeVisible();
    expect(screen.getByText("current events error")).toBeVisible();
    expect(screen.queryByText("obsolete earnings")).toBeNull();
    m.earnings.mockResolvedValueOnce(earningsPage("recovered", null));
    m.events.mockResolvedValueOnce(eventsPage("recovered event", null));
    for (const button of screen.getAllByRole("button", { name: "Try again" }))
      await userEvent.click(button);
    expect(
      await screen.findByRole("link", { name: "recovered" }),
    ).toBeVisible();
    expect(
      await screen.findByRole("cell", { name: /recovered event/ }),
    ).toBeVisible();
  });
}

for (const failure of [false, true]) {
  it(`obsolete pagination finalizers cannot clear current loading on either screen (${failure ? "failure" : "success"})`, async () => {
    const oldE = deferred<ReturnType<typeof earningsPage>>();
    const oldA = deferred<ReturnType<typeof eventsPage>>();
    const nextE = deferred<ReturnType<typeof earningsPage>>();
    const nextA = deferred<ReturnType<typeof eventsPage>>();
    m.earnings
      .mockResolvedValueOnce(earningsPage("initial"))
      .mockReturnValueOnce(oldE.promise)
      .mockResolvedValueOnce(earningsPage("current"))
      .mockReturnValueOnce(nextE.promise);
    m.events
      .mockResolvedValueOnce(eventsPage("initial event"))
      .mockReturnValueOnce(oldA.promise)
      .mockResolvedValueOnce(eventsPage("current event"))
      .mockReturnValueOnce(nextA.promise);
    render(
      <MemoryRouter>
        <Earnings />
        <AdminPage />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more earnings" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more events" }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Payout status"),
      "paid",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh events" }),
    );
    await screen.findByText("€123.45");
    await screen.findByRole("cell", { name: /current event/ });
    await userEvent.click(
      screen.getByRole("button", { name: "Load more earnings" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Load more events" }),
    );
    await act(async () => {
      if (failure) {
        oldE.reject(new Error("obsolete"));
        oldA.reject(new Error("obsolete"));
      } else {
        oldE.resolve(earningsPage("obsolete", null));
        oldA.resolve(eventsPage("obsolete", null));
      }
    });
    expect(screen.getAllByRole("button", { name: "Loading…" })).toHaveLength(2);
    for (const button of screen.getAllByRole("button", { name: "Loading…" }))
      expect(button).toBeDisabled();
    await act(async () => {
      nextE.resolve(earningsPage("recovered", null));
      nextA.resolve(eventsPage("recovered event", null));
    });
    expect(
      await screen.findByRole("link", { name: "recovered" }),
    ).toBeVisible();
    expect(
      await screen.findByRole("cell", { name: /recovered event/ }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Loading…" })).toBeNull();
  });
}
