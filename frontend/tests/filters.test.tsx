import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StayResults } from "../src/discovery/StayResults";
import { FiltersDrawer } from "../src/discovery/FiltersDrawer";
import { SearchForm } from "../src/discovery/SearchForm";
import {
  activeFilterCount,
  applyFilters,
  emptyFilters,
  euroCents,
  readFilters,
  validateFilters,
} from "../src/discovery/filters";
import type { PublicSummary } from "../src/discovery/api";
const mocks = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock("../src/discovery/api", () => ({ discoveryApi: mocks }));
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: new Date("2026-10-30T10:00:00Z"),
    error: "",
    refresh: vi.fn(),
  }),
}));
const summary: PublicSummary = {
  id: "one",
  title: "First stay",
  destination: "Lisbon",
  property_type: "house",
  capacity: 4,
  bedrooms: 2,
  beds: 2,
  baths: 1,
  nightly_minor: 10000,
  cleaning_minor: 0,
  booking_mode: "instant",
  photos: [],
  stay_price: null,
  demo_label: null,
};
function Location() {
  return <output aria-label="Current URL">{useLocation().search}</output>;
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.search.mockResolvedValue({ items: [summary], next_cursor: null });
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
});
describe("filter URL contract", () => {
  it("converts EUR exactly and rejects malformed or inverted ranges", () => {
    expect(euroCents("19.99")).toBe(1999);
    expect(euroCents("0.01")).toBe(1);
    expect(euroCents("100000")).toBe(10000000);
    for (const input of ["-1", "1e2", "1.999", "1,50", "NaN", "100000.01"])
      expect(() => euroCents(input)).toThrow();
    expect(
      validateFilters({ ...emptyFilters(), minimum: "100.01", maximum: "100" }),
    ).toHaveProperty("maximum");
  });
  it("preserves search/category/repeated amenities and resets only filter fields/cursor", () => {
    const params = new URLSearchParams(
      "destination=Lisbon&check_in=2026-11-15&check_out=2026-11-20&guests=2&category=cabins&amenity=wifi&amenity=kitchen&cursor=old",
    );
    const draft = {
      ...readFilters(params),
      minimum: "19.99",
      maximum: "200",
      place: "entire",
    };
    const next = applyFilters(params, draft);
    expect(next.getAll("amenity")).toEqual(["wifi", "kitchen"]);
    expect(next.get("min_price_minor")).toBe("1999");
    expect(next.get("cursor")).toBeNull();
    expect(next.get("category")).toBe("cabins");
    expect(next.get("check_in")).toBe("2026-11-15");
    expect(activeFilterCount(next)).toBe(4);
    const cleared = applyFilters(next, emptyFilters());
    expect(cleared.get("destination")).toBe("Lisbon");
    expect(cleared.get("guests")).toBe("2");
    expect(cleared.get("category")).toBe("cabins");
    expect(activeFilterCount(cleared)).toBe(0);
  });
  it("preserves committed filter repetitions when submitting search", async () => {
    render(
      <MemoryRouter>
        <SearchForm
          initial={{
            destination: "Lisbon",
            check_in: "",
            check_out: "",
            guests: "2",
          }}
          preserveQuery="amenity=wifi&amenity=kitchen&min_price_minor=100&min_price_minor=200&cursor=old"
        />
        <Location />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Search stays" }));
    const next = new URLSearchParams(
      screen.getByLabelText("Current URL").textContent!,
    );
    expect(next.getAll("amenity")).toEqual(["wifi", "kitchen"]);
    expect(next.getAll("min_price_minor")).toEqual(["100", "200"]);
    expect(next.get("cursor")).toBeNull();
  });
});
describe("drawer draft boundaries", () => {
  it("validates fields and keeps Clear all unapplied until Show stays", async () => {
    const apply = vi.fn(),
      close = vi.fn();
    render(
      <FiltersDrawer
        params={
          new URLSearchParams(
            "place_group=entire&min_price_minor=1000&amenity=wifi",
          )
        }
        onApply={apply}
        onClose={close}
      />,
    );
    expect(screen.getByRole("radio", { name: "Entire place" })).toBeChecked();
    await userEvent.clear(screen.getByLabelText("Minimum"));
    await userEvent.type(screen.getByLabelText("Minimum"), "100.01");
    await userEvent.type(screen.getByLabelText("Maximum"), "100");
    await userEvent.click(screen.getByRole("button", { name: "Show stays" }));
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Maximum")).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole("radio", { name: "Any type" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Show stays" }));
    expect(apply).toHaveBeenCalledWith(emptyFilters());
  });
  it("uses full-range minimum counters with Any at zero and disabled endpoints", async () => {
    const apply = vi.fn();
    render(
      <FiltersDrawer
        params={new URLSearchParams()}
        onApply={apply}
        onClose={vi.fn()}
      />,
    );
    for (const [label, maximum] of [
      ["bedrooms", 20],
      ["beds", 30],
    ] as const) {
      const decrease = screen.getByRole("button", {
        name: `Decrease minimum ${label}`,
      });
      const increase = screen.getByRole("button", {
        name: `Increase minimum ${label}`,
      });
      const value = screen.getByLabelText(`Minimum ${label} value`);
      expect(value).toHaveTextContent("Any");
      expect(decrease).toBeDisabled();
      for (let count = 1; count <= maximum; count++) {
        fireEvent.click(increase);
        expect(value).toHaveTextContent(`${count}+`);
      }
      expect(increase).toBeDisabled();
      expect(decrease).toBeEnabled();
    }
    await userEvent.click(screen.getByRole("button", { name: "Show stays" }));
    expect(apply).toHaveBeenCalledWith({
      ...emptyFilters(),
      bedrooms: "20",
      beds: "30",
    });
    expect(
      applyFilters(new URLSearchParams(), apply.mock.calls[0][0]).toString(),
    ).toBe("min_bedrooms=20&min_beds=30");
    for (const [label, maximum] of [
      ["bedrooms", 20],
      ["beds", 30],
    ] as const) {
      const decrease = screen.getByRole("button", {
        name: `Decrease minimum ${label}`,
      });
      for (let count = maximum; count > 0; count--) fireEvent.click(decrease);
      expect(decrease).toBeDisabled();
      expect(screen.getByLabelText(`Minimum ${label} value`)).toHaveTextContent(
        "Any",
      );
    }
  });
  it("keeps counter changes draft-only when the drawer is closed", async () => {
    const apply = vi.fn(),
      close = vi.fn();
    render(
      <FiltersDrawer
        params={new URLSearchParams("min_bedrooms=6&min_beds=12")}
        onApply={apply}
        onClose={close}
      />,
    );
    expect(screen.getByLabelText("Minimum bedrooms value")).toHaveTextContent(
      "6+",
    );
    expect(screen.getByLabelText("Minimum beds value")).toHaveTextContent(
      "12+",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Increase minimum bedrooms" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Decrease minimum beds" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close filters" }),
    );
    expect(close).toHaveBeenCalledOnce();
    expect(apply).not.toHaveBeenCalled();
  });
  it("wraps the dialog edges without overriding native interior keyboard behavior", () => {
    render(
      <FiltersDrawer
        params={new URLSearchParams()}
        onApply={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const close = screen.getByRole("button", { name: "Close filters" });
    const apply = screen.getByRole("button", { name: "Show stays" });
    close.focus();
    expect(fireEvent.keyDown(close, { key: "Tab", shiftKey: true })).toBe(
      false,
    );
    expect(apply).toHaveFocus();
    expect(fireEvent.keyDown(apply, { key: "Tab" })).toBe(false);
    expect(close).toHaveFocus();
    const minimum = screen.getByLabelText("Minimum");
    minimum.focus();
    expect(fireEvent.keyDown(minimum, { key: "Tab", shiftKey: true })).toBe(
      true,
    );
    expect(minimum).toHaveFocus();
    apply.setAttribute("disabled", "");
    close.focus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Clear all" })).toHaveFocus();
  });
  it("closes/cancels without applying draft changes", async () => {
    const apply = vi.fn(),
      close = vi.fn();
    render(
      <FiltersDrawer
        params={new URLSearchParams()}
        onApply={apply}
        onClose={close}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Wifi" }));
    fireEvent(
      screen.getByRole("dialog", { name: "Filters" }),
      new Event("cancel", { bubbles: true, cancelable: true }),
    );
    expect(close).toHaveBeenCalledTimes(1);
    expect(apply).not.toHaveBeenCalled();
  });
});
describe("results category toolbar", () => {
  it("uses a compact category select while preserving filters and resetting cursor", async () => {
    render(
      <MemoryRouter
        initialEntries={[
          "/stays?destination=Lisbon&category=cabins&amenity=wifi&amenity=kitchen&min_beds=3&cursor=old",
        ]}
      >
        <StayResults />
        <Location />
      </MemoryRouter>,
    );
    expect(
      screen.queryByRole("navigation", { name: "Stay categories" }),
    ).toBeNull();
    const category = screen.getByRole("combobox", { name: "Stay category" });
    expect(category).toHaveValue("cabins");
    await userEvent.selectOptions(category, "design");
    let params = new URLSearchParams(
      screen.getByLabelText("Current URL").textContent!,
    );
    expect(params.get("category")).toBe("design");
    expect(params.get("destination")).toBe("Lisbon");
    expect(params.getAll("amenity")).toEqual(["wifi", "kitchen"]);
    expect(params.get("min_beds")).toBe("3");
    expect(params.has("cursor")).toBe(false);
    await userEvent.selectOptions(category, "");
    params = new URLSearchParams(
      screen.getByLabelText("Current URL").textContent!,
    );
    expect(params.has("category")).toBe(false);
    expect(params.getAll("amenity")).toEqual(["wifi", "kitchen"]);
  });
});
describe("pagination request ownership", () => {
  it("ignores an obsolete page even after navigating A → B → A", async () => {
    let resolveOld!: (value: {
      items: PublicSummary[];
      next_cursor: null;
    }) => void;
    mocks.search.mockImplementation((query: string) => {
      const params = new URLSearchParams(query);
      if (params.has("cursor"))
        return new Promise((resolve) => {
          resolveOld = resolve;
        });
      return Promise.resolve({
        items: [
          {
            ...summary,
            title: params.get("destination") === "B" ? "B stay" : "A stay",
          },
        ],
        next_cursor: params.get("destination") === "B" ? null : "next",
      });
    });
    render(
      <MemoryRouter
        initialEntries={["/stays?destination=A&amenity=wifi&amenity=kitchen"]}
      >
        <Link to="/stays?destination=B">Go B</Link>
        <Link to="/stays?destination=A&amenity=wifi&amenity=kitchen">Go A</Link>
        <StayResults />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Load more stays" }),
    );
    const sent = new URLSearchParams(mocks.search.mock.calls[1][0]);
    expect(sent.getAll("amenity")).toEqual(["wifi", "kitchen"]);
    await userEvent.click(screen.getByRole("link", { name: "Go B" }));
    await screen.findByRole("heading", { name: "B stay" });
    await userEvent.click(screen.getByRole("link", { name: "Go A" }));
    await screen.findByRole("heading", { name: "A stay" });
    await act(async () =>
      resolveOld({
        items: [{ ...summary, id: "obsolete", title: "Obsolete page" }],
        next_cursor: null,
      }),
    );
    expect(screen.queryByRole("heading", { name: "Obsolete page" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Load more stays" }),
    ).toBeEnabled();
  });
  it("applies home filters without dropping category/search", async () => {
    render(
      <MemoryRouter
        initialEntries={["/?destination=Lisbon&category=cabins&guests=2"]}
      >
        <StayResults explore />
        <Location />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    const drawer = screen.getByRole("dialog", { name: "Filters" });
    await userEvent.click(
      within(drawer).getByRole("radio", { name: "Private room" }),
    );
    await userEvent.click(
      within(drawer).getByRole("checkbox", { name: "Kitchen" }),
    );
    await userEvent.click(
      within(drawer).getByRole("button", { name: "Show stays" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const params = new URLSearchParams(
      screen.getByLabelText("Current URL").textContent!,
    );
    expect(params.get("place_group")).toBe("private");
    expect(params.get("category")).toBe("cabins");
    expect(params.get("destination")).toBe("Lisbon");
    expect(params.getAll("amenity")).toEqual(["kitchen"]);
    expect(
      screen.getByRole("button", { name: "Filters (2 active)" }),
    ).toBeVisible();
  });
});
