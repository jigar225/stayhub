import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { TimezonePicker } from "../src/listings/TimezonePicker";
import { useState } from "react";
const mocks = vi.hoisted(() => ({ zones: vi.fn() }));
vi.mock("../src/listings/api", () => ({ timezoneApi: mocks.zones }));
const options = [
  { value: "Asia/Kolkata", label: "Asia/Kolkata — Kolkata" },
  { value: "US/Eastern", label: "US/Eastern — Eastern" },
  { value: "UTC", label: "UTC — UTC" },
];
function Form({ initial = "US/Eastern" }) {
  const [value, setValue] = useState(initial);
  return <TimezonePicker value={value} onChange={setValue} />;
}
beforeEach(() => {
  mocks.zones.mockReset();
  mocks.zones.mockResolvedValue({ items: options });
});
it("preserves a valid saved alias and chooses city search using keyboard", async () => {
  render(<Form />);
  const input = screen.getByRole("combobox", { name: "Timezone" });
  expect(input).toHaveValue("US/Eastern");
  fireEvent.focus(input);
  expect(
    await screen.findByRole("option", { name: "US/Eastern — Eastern" }),
  ).toBeVisible();
  fireEvent.change(input, { target: { value: "kolkata" } });
  expect(
    screen.getByRole("option", { name: "Asia/Kolkata — Kolkata" }),
  ).toBeVisible();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input).toHaveValue("Asia/Kolkata");
  expect(input).toHaveAttribute("aria-expanded", "false");
});
it("keeps saved UTC on catalog failure and allows retry without changing it", async () => {
  mocks.zones.mockRejectedValueOnce(new Error("offline"));
  render(<Form initial="UTC" />);
  expect(
    await screen.findByRole("button", { name: "Retry timezone choices" }),
  ).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveValue("UTC");
  fireEvent.click(
    screen.getByRole("button", { name: "Retry timezone choices" }),
  );
  await waitFor(() => expect(mocks.zones).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(
      screen.queryByText(/Timezone choices could not load/),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("combobox")).toHaveValue("UTC");
});
