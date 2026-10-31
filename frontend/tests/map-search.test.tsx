import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { StayResults } from "../src/discovery/StayResults";
import { listingsQuery, boundsQuery } from "../src/discovery/mapSearch";
import type { ResultsMapProps } from "../src/discovery/ResultsMap";
const mocks = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock("../src/discovery/api", () => ({
  discoveryApi: { search: mocks.search },
}));
vi.mock("../src/api/businessTime", () => ({
  useBusinessTime: () => ({
    now: new Date("2026-10-31T00:00:00Z"),
    error: "",
    refresh: vi.fn(),
  }),
}));
vi.mock("../src/discovery/ResultsMapPanel", () => ({
  ResultsMapPanel: ({ items, onBounds, selected }: ResultsMapProps) => (
    <div>
      <span data-testid="pins">
        {items.map((item) => item.title).join(",")}|{selected}
      </span>
      <button
        onClick={() => onBounds({ west: 1, south: 0, east: 2, north: 1 })}
      >
        Pan A
      </button>
      <button
        onClick={() => onBounds({ west: 3, south: 0, east: 4, north: 1 })}
      >
        Pan B
      </button>
    </div>
  ),
}));
function History() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="url">{location.search}</output>
      <button onClick={() => navigate(-1)}>Back</button>
    </>
  );
}
function setup(
  query = "view=map&destination=Lisbon&amenity=wifi&amenity=kitchen&guests=2",
) {
  render(
    <MemoryRouter initialEntries={[`/stays?${query}`]}>
      <StayResults />
      <History />
    </MemoryRouter>,
  );
}
function page(title: string) {
  return {
    items: [
      {
        id: title,
        title,
        destination: "Lisbon",
        property_type: "apartment",
        capacity: 2,
        beds: 1,
        baths: 1,
        nightly_minor: 12800,
        photos: [],
        stay_price: null,
        location: { latitude: 1, longitude: 2 },
      },
    ],
    next_cursor: null,
  };
}
beforeEach(() => {
  mocks.search.mockReset();
  mocks.search.mockResolvedValue(page("First"));
});
it("serializes map limits and preserves repeated filters while list mode includes unlocated stays", () => {
  const p = new URLSearchParams(
    "view=map&west=1&south=0&east=2&north=1&amenity=wifi&amenity=kitchen&cursor=old",
  );
  const q = new URLSearchParams(listingsQuery(p));
  expect(q.get("map")).toBe("true");
  expect(q.get("limit")).toBe("50");
  expect(q.has("cursor")).toBe(false);
  expect(q.getAll("amenity")).toEqual(["wifi", "kitchen"]);
  p.set("view", "list");
  const list = new URLSearchParams(listingsQuery(p));
  expect(list.has("west")).toBe(false);
  expect(list.has("map")).toBe(false);
  expect(
    boundsQuery({ north: 1, east: -179, south: -1, west: 179.123456 }),
  ).toEqual({ west: "179.12346", south: "-1", east: "-179", north: "1" });
});
it("switches view and history without losing filters", async () => {
  setup();
  await screen.findByTestId("pins");
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  await waitFor(() =>
    expect(screen.getByTestId("url")).toHaveTextContent("view=list"),
  );
  expect(screen.getByTestId("url")).toHaveTextContent(
    "amenity=wifi&amenity=kitchen",
  );
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await waitFor(() =>
    expect(screen.getByTestId("url")).toHaveTextContent("view=map"),
  );
});
it("manual pans do not fetch until explicit area search; late area response cannot restore stale pins", async () => {
  let resolveA!: (value: unknown) => void, resolveB!: (value: unknown) => void;
  mocks.search.mockImplementation((query: string) =>
    query.includes("west=1")
      ? new Promise((resolve) => {
          resolveA = resolve;
        })
      : query.includes("west=3")
        ? new Promise((resolve) => {
            resolveB = resolve;
          })
        : Promise.resolve(page("First")),
  );
  setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("First"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Pan A" }));
  expect(mocks.search).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Search this area" }));
  await waitFor(() => expect(resolveA).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Pan B" }));
  fireEvent.click(screen.getByRole("button", { name: "Search this area" }));
  await waitFor(() => expect(resolveB).toBeTypeOf("function"));
  await act(async () => resolveB(page("Newest")));
  expect(screen.getByTestId("pins")).toHaveTextContent("Newest");
  await act(async () => resolveA(page("Old")));
  expect(screen.getByTestId("pins")).toHaveTextContent("Newest");
  expect(screen.getByTestId("pins")).not.toHaveTextContent("Old");
});
it("debounces rapid movement while preserving committed filters", async () => {
  setup("view=map&move=true&amenity=wifi&guests=2");
  await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Pan A" }));
  fireEvent.click(screen.getByRole("button", { name: "Pan B" }));
  await waitFor(() =>
    expect(screen.getByTestId("url")).toHaveTextContent("west=3"),
  );
  expect(screen.getByTestId("url")).toHaveTextContent("amenity=wifi");
  expect(mocks.search).toHaveBeenCalledTimes(2);
});
