import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DateRangePicker } from "../src/discovery/DateRangePicker";
import { SearchForm } from "../src/discovery/SearchForm";
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: new Date("2026-10-30T10:00:00Z"),
    error: "",
    refresh: vi.fn(),
  }),
}));
const label = (day: string) =>
  new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${day}T12:00:00Z`));
function Harness({
  start = "2026-11-15",
  end = "2026-11-20",
  minimum = "2026-10-30",
  required = false,
  apply = vi.fn(),
}: {
  start?: string;
  end?: string;
  minimum?: string;
  required?: boolean;
  apply?: (range: { check_in: string; check_out: string }) => void;
}) {
  const [range, setRange] = useState({ check_in: start, check_out: end });
  return (
    <DateRangePicker
      checkIn={range.check_in}
      checkOut={range.check_out}
      minimum={minimum}
      requireDates={required}
      errors={{}}
      onApply={(next) => {
        setRange(next);
        apply(next);
      }}
    />
  );
}
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});
describe("controlled exact-date calendar", () => {
  it("shows two months, selects a cross-year range, and commits only after Apply", async () => {
    const apply = vi.fn();
    render(<Harness start="2026-12-30" end="2027-01-02" apply={apply} />);
    const trigger = screen.getByRole("button", { name: "Check in" });
    await userEvent.click(trigger);
    expect(screen.getAllByRole("grid")).toHaveLength(2);
    await userEvent.click(
      screen.getByRole("button", { name: label("2026-12-31") }),
    );
    expect(screen.getByText("Select check-out date")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: label("2027-01-03") }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("3 nights");
    expect(apply).not.toHaveBeenCalled();
    expect(trigger).toHaveTextContent("30 Dec 2026");
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    expect(apply).toHaveBeenCalledWith({
      check_in: "2026-12-31",
      check_out: "2027-01-03",
    });
    expect(trigger).toHaveTextContent("31 Dec 2026");
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("discards draft dates and Clear on Escape/outside, restoring focus", async () => {
    const apply = vi.fn();
    render(<Harness apply={apply} />);
    const trigger = screen.getByRole("button", { name: "Check in" });
    await userEvent.click(trigger);
    await userEvent.click(
      screen.getByRole("button", { name: label("2026-11-16") }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Clear dates" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveTextContent("15 Nov 2026");
    expect(trigger).toHaveFocus();
    expect(apply).not.toHaveBeenCalled();
    await userEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apply).not.toHaveBeenCalled();
  });
  it("enforces the minimum and a complete ordered range, and restarts when checkout precedes checkin", async () => {
    const apply = vi.fn();
    render(<Harness minimum="2026-11-15" required apply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Check out" }));
    expect(
      screen.getByRole("button", { name: label("2026-11-14") }),
    ).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: label("2026-11-15") }),
    );
    expect(screen.getByText("Select check-out date")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose both");
    expect(apply).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: label("2026-11-16") }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    expect(apply).toHaveBeenCalledWith({
      check_in: "2026-11-15",
      check_out: "2026-11-16",
    });
  });
  it("moves grid focus by day, week, week boundaries, month/year and clamps short months", async () => {
    render(
      <Harness start="2026-12-31" end="2027-01-02" minimum="2020-01-01" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    let focused = screen.getByRole("button", { name: label("2026-12-31") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "ArrowRight" });
    focused = screen.getByRole("button", { name: label("2027-01-01") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "Home" });
    focused = screen.getByRole("button", { name: label("2026-12-28") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "End" });
    focused = screen.getByRole("button", { name: label("2027-01-03") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "ArrowDown" });
    focused = screen.getByRole("button", { name: label("2027-01-10") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "PageDown", shiftKey: true });
    focused = screen.getByRole("button", { name: label("2028-01-10") });
    expect(focused).toHaveFocus();
    fireEvent.keyDown(focused, { key: "PageUp" });
    expect(
      screen.getByRole("button", { name: label("2027-12-10") }),
    ).toHaveFocus();
  });
  it("clamps PageDown across leap-day and non-leap-year boundaries", async () => {
    render(
      <Harness start="2028-01-31" end="2028-02-02" minimum="2020-01-01" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    fireEvent.keyDown(
      screen.getByRole("button", { name: label("2028-01-31") }),
      { key: "PageDown" },
    );
    const leap = screen.getByRole("button", { name: label("2028-02-29") });
    expect(leap).toHaveFocus();
    fireEvent.keyDown(leap, { key: "PageDown", shiftKey: true });
    expect(
      screen.getByRole("button", { name: label("2029-02-28") }),
    ).toHaveFocus();
  });
  it("keeps one readable month on narrow screens and navigates across December/January", async () => {
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    render(<Harness start="2026-12-31" end="2027-01-02" />);
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    expect(screen.getAllByRole("grid")).toHaveLength(1);
    expect(screen.getByRole("grid", { name: "December 2026" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("grid", { name: "January 2027" })).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Previous month" }),
    );
    expect(screen.getByRole("grid", { name: "December 2026" })).toBeVisible();
  });
  it("reconciles an open calendar when authoritative business minimum arrives later", async () => {
    const apply = vi.fn();
    const view = render(
      <DateRangePicker checkIn="" checkOut="" errors={{}} onApply={apply} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    view.rerender(
      <DateRangePicker
        checkIn=""
        checkOut=""
        minimum="2035-12-15"
        errors={{}}
        onApply={apply}
      />,
    );
    expect(screen.getByRole("grid", { name: "December 2035" })).toBeVisible();
    const minimum = screen.getByRole("button", { name: label("2035-12-15") });
    expect(minimum).toBeEnabled();
    expect(minimum).toHaveFocus();
    expect(
      screen.getByRole("button", { name: label("2035-12-14") }),
    ).toBeDisabled();
    expect(apply).not.toHaveBeenCalled();
  });
  it("dismisses with Escape after keyboard focus leaves the nonmodal calendar", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Check in" });
    await userEvent.click(trigger);
    const checkout = screen.getByRole("button", { name: "Check out" });
    checkout.focus();
    fireEvent.keyDown(checkout, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });
  it("allows clearing optional dates, but does not apply empty required detail dates", async () => {
    const apply = vi.fn();
    const view = render(<Harness apply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    await userEvent.click(screen.getByRole("button", { name: "Clear dates" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    expect(apply).toHaveBeenCalledWith({ check_in: "", check_out: "" });
    view.unmount();
    apply.mockClear();
    render(<Harness required apply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    await userEvent.click(screen.getByRole("button", { name: "Clear dates" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose both");
    expect(apply).not.toHaveBeenCalled();
  });
});
function Location() {
  return <output aria-label="URL">{useLocation().search}</output>;
}
it("preserves filters/category/search and invalidates a quote only on committed date edits", async () => {
  const dirty = vi.fn();
  render(
    <MemoryRouter>
      <SearchForm
        initial={{
          destination: "Lisbon",
          check_in: "2026-11-15",
          check_out: "2026-11-20",
          guests: "2",
        }}
        preserveQuery="category=cabins&amenity=wifi&amenity=kitchen&cursor=old"
        onDirty={dirty}
      />
      <Location />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Check in" }));
  await userEvent.click(
    screen.getByRole("button", { name: label("2026-11-16") }),
  );
  expect(dirty).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: label("2026-11-21") }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
  expect(dirty).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Search stays" }));
  const params = new URLSearchParams(screen.getByLabelText("URL").textContent!);
  expect(params.get("check_in")).toBe("2026-11-16");
  expect(params.get("check_out")).toBe("2026-11-21");
  expect(params.getAll("amenity")).toEqual(["wifi", "kitchen"]);
  expect(params.get("category")).toBe("cabins");
  expect(params.has("cursor")).toBe(false);
  expect(
    within(screen.getByRole("button", { name: "Check in" })).getByText(
      "16 Nov 2026",
    ),
  ).toBeVisible();
});
