import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Link, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StayResults } from "../src/discovery/StayResults";
import { StayDetail } from "../src/discovery/StayDetail";
import { SearchForm } from "../src/discovery/SearchForm";
import { PublicPhotos } from "../src/discovery/PublicPhotos";
import { MonthGrid } from "../src/calendar/MonthGrid";
import { monthCells } from "../src/calendar/monthCells";
import {
  earliestCheckIn,
  addDays,
  monthBounds,
  validateSearch,
} from "../src/discovery/dates";
import type { PublicSummary, PublicDetail, Quote } from "../src/discovery/api";
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: new Date("2026-10-30T10:00:00Z"),
    error: "",
    refresh: vi.fn(),
  }),
  refreshBusinessTime: vi.fn(),
}));
const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  photos: vi.fn(),
  detail: vi.fn(),
  quote: vi.fn(),
}));
vi.mock("../src/discovery/api", async (original) => ({
  ...(await original<typeof import("../src/discovery/api")>()),
  discoveryApi: mocks,
}));
const photo = {
  id: "photo",
  url: "http://storage/first",
  expires_at: "2026-11-01T00:00:00Z",
  width: 800,
  height: 600,
};
const summary: PublicSummary = {
  id: "stay",
  title: "Quiet Lisbon loft",
  destination: "Lisbon",
  property_type: "apartment",
  capacity: 2,
  bedrooms: 1,
  beds: 1,
  baths: 1,
  nightly_minor: 12800,
  cleaning_minor: 3500,
  booking_mode: "instant",
  photos: [photo],
  stay_price: null,
  demo_label: null,
};
const detail: PublicDetail = {
  ...summary,
  description: "A calm bright place.",
  amenities: ["Wifi"],
  house_rules: ["Quiet after 11"],
  timezone: "Europe/Lisbon",
  check_in_time: "15:00",
  check_out_time: "11:00",
  host_name: "Host",
  policy: {
    id: "policy",
    name: "Moderate",
    version: 1,
    terms: "Full refund at least five days before check-in.",
  },
};
const quote: Quote = {
  nights: 5,
  nightly_minor: 12800,
  nights_minor: 64000,
  cleaning_minor: 3500,
  subtotal_minor: 67500,
  guest_fee_minor: 9450,
  total_minor: 76950,
  currency: "EUR",
  listing_id: "stay",
  check_in: "2026-11-15",
  check_out: "2026-11-20",
  guests: 2,
  booking_mode: "instant",
  policy: detail.policy,
  scheduled_check_in: "2026-11-15T15:00:00Z",
  scheduled_check_out: "2026-11-20T11:00:00Z",
  expires_at: "2026-10-30T11:00:00Z",
  quote_token: "test-quote",
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.search.mockResolvedValue({ items: [summary], next_cursor: null });
  mocks.detail.mockResolvedValue({ listing: detail });
  mocks.quote.mockResolvedValue({ quote });
});
describe("public discovery recovery and date semantics", () => {
  it("validates paired dates and guests and preserves form input", async () => {
    const submit = vi.fn();
    render(
      <MemoryRouter>
        <SearchForm
          initial={{
            destination: "Lisbon",
            check_in: "2026-11-15",
            check_out: "",
            guests: "2",
          }}
          onSubmit={submit}
        />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Search stays" }));
    expect(screen.getByText("Choose a valid check-out date.")).toBeVisible();
    expect(screen.getByLabelText("Where")).toHaveValue("Lisbon");
    expect(submit).not.toHaveBeenCalled();
    expect(
      validateSearch({
        destination: "",
        check_in: "2026-11-20",
        check_out: "2026-11-15",
        guests: "0",
      }),
    ).toEqual({
      check_out: "Check-out must be after check-in.",
      guests: "Choose between 1 and 30 guests.",
    });
  });
  it("ignores a slower prior search response after query navigation", async () => {
    let resolve!: (value: {
      items: PublicSummary[];
      next_cursor: null;
    }) => void;
    mocks.search
      .mockReturnValueOnce(
        new Promise((done) => {
          resolve = done;
        }),
      )
      .mockResolvedValueOnce({
        items: [
          { ...summary, title: "New Kyoto search", destination: "Kyoto" },
        ],
        next_cursor: null,
      });
    render(
      <MemoryRouter initialEntries={["/stays?destination=Lisbon"]}>
        <Link to="/stays?destination=Kyoto">Search Kyoto</Link>
        <StayResults />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("link", { name: "Search Kyoto" }));
    expect(
      await screen.findByRole("heading", { name: "New Kyoto search" }),
    ).toBeVisible();
    await act(async () => resolve({ items: [summary], next_cursor: null }));
    expect(
      screen.queryByRole("heading", { name: "Quiet Lisbon loft" }),
    ).toBeNull();
    expect(
      screen.getByRole("heading", { name: "New Kyoto search" }),
    ).toBeVisible();
  });
  it("offers the next bounded page when the first filtered page is empty but has a cursor", async () => {
    mocks.search
      .mockResolvedValueOnce({ items: [], next_cursor: "next-page" })
      .mockResolvedValueOnce({ items: [summary], next_cursor: null });
    render(
      <MemoryRouter>
        <StayResults />
      </MemoryRouter>,
    );
    const more = await screen.findByRole("button", { name: "Load more stays" });
    expect(
      screen.queryByRole("heading", { name: "No stays match your plans" }),
    ).toBeNull();
    await userEvent.click(more);
    expect(
      await screen.findByRole("heading", { name: summary.title }),
    ).toBeVisible();
    expect(mocks.search.mock.calls[1][0]).toContain("cursor=next-page");
  });
  it("shows search failures with an actionable real retry, never sample data", async () => {
    mocks.search.mockRejectedValueOnce(
      new Error("Storage temporarily unavailable"),
    );
    render(
      <MemoryRouter>
        <StayResults />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Storage temporarily unavailable",
    );
    expect(
      screen.queryByRole("heading", { name: "Quiet Lisbon loft" }),
    ).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", { name: "Quiet Lisbon loft" }),
    ).toBeVisible();
  });
  it("shows authoritative quote totals and hides the previous price when inputs change", async () => {
    render(
      <MemoryRouter
        initialEntries={[
          "/stays/stay?check_in=2026-11-15&check_out=2026-11-20&guests=2",
        ]}
      >
        <Routes>
          <Route path="/stays/:id" element={<StayDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("€769.50")).toBeVisible();
    expect(screen.getByText("€94.50")).toBeVisible();
    expect(screen.getByText(detail.policy.terms)).toBeVisible();
    expect(screen.getByRole("link", { name: "Reserve" })).toHaveAttribute(
      "href",
      expect.stringContaining("/checkout/stay?check_in=2026-11-15"),
    );
    await userEvent.clear(screen.getByLabelText("Guests"));
    await userEvent.type(screen.getByLabelText("Guests"), "3");
    expect(screen.queryByText("€769.50")).toBeNull();
    expect(mocks.quote).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Check price" }));
    await waitFor(() => expect(mocks.quote).toHaveBeenCalledTimes(2));
    expect(mocks.quote).toHaveBeenLastCalledWith("stay", {
      check_in: "2026-11-15",
      check_out: "2026-11-20",
      guests: 3,
    });
  });
  it("uses provided image URLs without per-photo requests, batches concurrent failures and bounds automatic renewal", async () => {
    mocks.photos.mockResolvedValue({
      items: [
        { ...photo, url: "http://storage/renewed" },
        { ...photo, id: "second", url: "http://storage/second-renewed" },
      ],
    });
    render(
      <PublicPhotos
        listingId="stay"
        photos={[
          photo,
          { ...photo, id: "second", url: "http://storage/second" },
        ]}
        title="Loft"
        gallery
      />,
    );
    expect(mocks.photos).not.toHaveBeenCalled();
    const images = screen.getAllByRole("img");
    fireEvent.error(images[0]);
    fireEvent.error(images[1]);
    await waitFor(() =>
      expect(screen.getAllByRole("img")[0]).toHaveAttribute(
        "src",
        "http://storage/renewed",
      ),
    );
    expect(mocks.photos).toHaveBeenCalledTimes(1);
    fireEvent.error(screen.getAllByRole("img")[0]);
    expect(
      await screen.findByRole("button", { name: "Retry photos" }),
    ).toBeVisible();
    expect(mocks.photos).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Retry photos" }));
    expect(mocks.photos).toHaveBeenCalledTimes(2);
  });
  it("counts local calendar days through DST and excludes checkout from blocks", () => {
    expect(addDays("2026-03-28", 2)).toBe("2026-03-30");
    expect(monthBounds("2026-03")).toEqual({
      start: "2026-03-01",
      end: "2026-04-01",
    });
    expect(monthCells("2028-02").filter(Boolean)).toHaveLength(29);
    render(
      <MonthGrid
        month="2026-11"
        blocks={[
          {
            id: "block",
            kind: "block",
            check_in: "2026-11-15",
            check_out: "2026-11-17",
          },
        ]}
        selectedStart=""
        selectedEnd=""
        onSelect={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "15 Nov 2026, Blocked" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "16 Nov 2026, Blocked" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "17 Nov 2026, Available" }),
    ).toBeVisible();
  });
});

it("uses listing-local scheduling and exact instant/request boundaries for selectable dates", () => {
  const schedule = {
    timezone: "Asia/Kolkata",
    booking_mode: "instant" as const,
    check_in_time: "15:00",
  };
  expect(earliestCheckIn(schedule, new Date("2027-01-15T09:29:59.999Z"))).toBe(
    "2027-01-15",
  );
  expect(earliestCheckIn(schedule, new Date("2027-01-15T09:30:00Z"))).toBe(
    "2027-01-16",
  );
  expect(earliestCheckIn(schedule, new Date("2027-01-15T10:00:00Z"))).toBe(
    "2027-01-16",
  );
  const request = { ...schedule, booking_mode: "request" as const };
  expect(earliestCheckIn(request, new Date("2027-01-14T09:30:00Z"))).toBe(
    "2027-01-15",
  );
  expect(earliestCheckIn(request, new Date("2027-01-14T09:30:00.001Z"))).toBe(
    "2027-01-16",
  );
  expect(earliestCheckIn(undefined, new Date("2027-01-15T01:00:00Z"))).toBe(
    "2027-01-14",
  );
});
it("restricts pickers, rejects typed dates and asks for checkout again after check-in changes", async () => {
  const submit = vi.fn();
  render(
    <MemoryRouter>
      <SearchForm
        initial={{
          destination: "",
          check_in: "2027-01-15",
          check_out: "2027-01-16",
          guests: "1",
        }}
        onSubmit={submit}
        schedule={{
          timezone: "Asia/Tokyo",
          booking_mode: "instant",
          check_in_time: "15:00",
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByLabelText("Check out")).toHaveAttribute(
    "min",
    "2027-01-16",
  );
  fireEvent.change(screen.getByLabelText("Check in"), {
    target: { value: "2027-01-16" },
  });
  expect(screen.getByLabelText("Check out")).toHaveValue("");
  expect(screen.getByText(/Check-in changed/)).toBeVisible();
  fireEvent.change(screen.getByLabelText("Check in"), {
    target: { value: "2000-01-01" },
  });
  fireEvent.change(screen.getByLabelText("Check out"), {
    target: { value: "2000-01-02" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Search stays" }));
  expect(screen.getByText(/Choose a later check-in date/)).toBeVisible();
  expect(submit).not.toHaveBeenCalled();
});
