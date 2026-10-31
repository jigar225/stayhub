import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  Notifications,
  NotificationBell,
} from "../src/notifications/Notifications";
const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/api/client", () => ({ authenticated: mocks.api }));
vi.mock("../src/auth/useSession", () => ({
  useSession: () => ({ user: { id: "guest" } }),
}));
const page = {
  items: [
    {
      id: 42,
      title: "Your reservation was accepted",
      href: "/trips/reservation-one",
      kind: "accepted",
      created_at: "2026-10-31T12:00:00Z",
      read_at: null,
    },
  ],
  unread_count: 1,
  cutoff: 42,
  next_cursor: null,
};
beforeEach(() => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue(page);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("uses the loaded notification cutoff and links to the real source", async () => {
  render(
    <MemoryRouter>
      <Notifications />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("link", { name: page.items[0].title }),
  ).toHaveAttribute("href", "/trips/reservation-one");
  fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
  await waitFor(() =>
    expect(mocks.api).toHaveBeenCalledWith("/me/notifications/read-all", {
      method: "POST",
      body: JSON.stringify({ cutoff: 42 }),
    }),
  );
  // A later arrival remains unread in the reloaded server projection.
  expect(await screen.findByText("1 unread")).toBeInTheDocument();
  await waitFor(() => expect(mocks.api).toHaveBeenCalledTimes(3));
});
it("offers retry after list failure", async () => {
  mocks.api.mockRejectedValueOnce(new Error("Notifications unavailable"));
  render(
    <MemoryRouter>
      <Notifications />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("Notifications unavailable"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
  expect(
    await screen.findByRole("link", { name: page.items[0].title }),
  ).toBeInTheDocument();
});
it("does not poll hidden tabs and cancels on unmount", () => {
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  const view = render(
    <MemoryRouter>
      <NotificationBell />
    </MemoryRouter>,
  );
  expect(mocks.api).not.toHaveBeenCalled();
  view.unmount();
  fireEvent(document, new Event("visibilitychange"));
  expect(mocks.api).not.toHaveBeenCalled();
});
