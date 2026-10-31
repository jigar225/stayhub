import { useState } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocationEditor } from "../src/location/LocationEditor";
import { PublicLocation } from "../src/location/PublicLocation";
import { changedFields, toForm } from "../src/listings/form";
import type { Listing } from "../src/listings/api";
const mocks = vi.hoisted(() => ({
  autocomplete: vi.fn(),
  publicLocation: vi.fn(),
}));
vi.mock("../src/location/api", () => ({ locationApi: mocks }));
vi.mock("../src/location/LocationMap", () => ({
  default: ({
    point,
    onChange,
    approximate,
  }: {
    point: { latitude: number; longitude: number } | null;
    onChange?: (point: { latitude: number; longitude: number }) => void;
    approximate?: boolean;
  }) => (
    <div data-testid="map">
      {approximate ? "Approximate map" : "Host map"}
      {point && (
        <span>
          {point.latitude},{point.longitude}
        </span>
      )}
      {onChange && (
        <button onClick={() => onChange({ latitude: 38.72, longitude: -9.14 })}>
          Move pin
        </button>
      )}
    </div>
  ),
}));
function Editor({
  initial = { address: "", latitude: "", longitude: "" },
}: {
  initial?: { address: string; latitude: string; longitude: string };
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <LocationEditor {...value} disabled={false} onChange={setValue} />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}
const suggestion = {
  display_address: "Rua Augusta, Lisbon",
  latitude: 38.7101,
  longitude: -9.1372,
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.autocomplete.mockResolvedValue({ items: [suggestion] });
  mocks.publicLocation.mockResolvedValue({ location: null });
});
afterEach(() => vi.useRealTimers());
async function tick() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(360);
  });
}
describe("host location", () => {
  it("searches only deliberate input of at least three characters after a pause, then selects by keyboard and preserves unit", async () => {
    vi.useFakeTimers();
    render(<Editor />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "Ru" } });
    await tick();
    expect(mocks.autocomplete).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "Rua, Apt 4" } });
    expect(mocks.autocomplete).not.toHaveBeenCalled();
    await tick();
    expect(mocks.autocomplete).toHaveBeenCalledOnce();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input).toHaveValue("Rua Augusta, Lisbon, Apt 4");
    expect(screen.getByTestId("value")).toHaveTextContent(
      '"latitude":"38.7101"',
    );
    fireEvent.blur(input);
    await tick();
    expect(mocks.autocomplete).toHaveBeenCalledOnce();
  });
  it("discards late responses including A → B → A and closes on Escape", async () => {
    vi.useFakeTimers();
    let first!: (value: unknown) => void;
    mocks.autocomplete
      .mockReturnValueOnce(
        new Promise((resolve) => {
          first = resolve;
        }),
      )
      .mockResolvedValueOnce({
        items: [{ ...suggestion, display_address: "New query result" }],
      })
      .mockResolvedValueOnce({
        items: [{ ...suggestion, display_address: "Newest Rua result" }],
      });
    render(<Editor />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "Rua" } });
    await tick();
    fireEvent.change(input, { target: { value: "Lisbon" } });
    await tick();
    expect(screen.getByRole("option")).toHaveTextContent("New query result");
    fireEvent.change(input, { target: { value: "Rua" } });
    await tick();
    expect(screen.getByRole("option")).toHaveTextContent("Newest Rua result");
    await act(async () => first({ items: [suggestion] }));
    expect(screen.getByRole("option")).toHaveTextContent("Newest Rua result");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
  it("invalidates a selected pin on address edit and allows manual reconfirmation after provider failure", async () => {
    vi.useFakeTimers();
    mocks.autocomplete.mockRejectedValue(
      new Error("Address suggestions are unavailable."),
    );
    render(
      <Editor
        initial={{
          address: "Saved address",
          latitude: "38.71",
          longitude: "-9.13",
        }}
      />,
    );
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "New address" },
    });
    expect(screen.getByTestId("value")).toHaveTextContent('"latitude":""');
    await tick();
    expect(
      screen.getByText("Address suggestions are unavailable."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Latitude"), {
      target: { value: "38.72" },
    });
    fireEvent.change(screen.getByLabelText("Longitude"), {
      target: { value: "-9.14" },
    });
    expect(screen.getByTestId("value")).toHaveTextContent('"latitude":""');
    fireEvent.click(screen.getByRole("button", { name: "Confirm pin" }));
    expect(screen.getByTestId("value")).toHaveTextContent(
      '"latitude":"38.720000"',
    );
    expect(mocks.autocomplete).toHaveBeenCalledOnce();
  });
  it("selects by pointer, allows map adjustment, and clears both coordinates", async () => {
    vi.useFakeTimers();
    render(<Editor />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "Rua" },
    });
    await tick();
    fireEvent.click(screen.getByRole("option"));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Move pin" }));
    expect(screen.getByTestId("value")).toHaveTextContent(
      '"longitude":"-9.140000"',
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove pin" }));
    expect(screen.getByTestId("value")).toHaveTextContent('"longitude":""');
  });
  it("serializes coordinates atomically even when only one differs", () => {
    const listing = { latitude: 38.71, longitude: -9.13 } as Listing;
    const form = toForm(listing);
    form.latitude = "38.72";
    expect(changedFields(form, listing)).toEqual({
      latitude: 38.72,
      longitude: -9.13,
    });
    form.latitude = "";
    form.longitude = "";
    expect(changedFields(form, listing)).toEqual({
      latitude: null,
      longitude: null,
    });
    form.latitude = "Infinity";
    expect(() => changedFields(form, listing)).toThrow();
  });
});
describe("public location boundary", () => {
  it("renders only the approximate API point and supports null historical locations", async () => {
    mocks.publicLocation.mockResolvedValueOnce({
      location: {
        latitude: 38.71,
        longitude: -9.14,
        grid_degrees: 0.01,
        radius_meters: 800,
        max_zoom: 12,
      },
    });
    const { rerender } = render(<PublicLocation listingId="one" />);
    expect(await screen.findByText("Approximate location")).toBeInTheDocument();
    expect(await screen.findByTestId("map")).toHaveTextContent("38.71,-9.14");
    rerender(<PublicLocation listingId="two" />);
    await waitFor(() =>
      expect(
        screen.queryByText("Approximate location"),
      ).not.toBeInTheDocument(),
    );
    expect(mocks.publicLocation).toHaveBeenCalledTimes(2);
  });
  it("keeps failures isolated and retries without stale errors on navigation", async () => {
    mocks.publicLocation.mockRejectedValueOnce(new Error("offline"));
    const { rerender } = render(<PublicLocation listingId="one" />);
    expect(
      await screen.findByRole("button", { name: "Retry location" }),
    ).toBeInTheDocument();
    rerender(<PublicLocation listingId="two" />);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Retry location" }),
      ).not.toBeInTheDocument(),
    );
  });
});
