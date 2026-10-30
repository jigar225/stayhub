import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { ListingWizard } from "../src/listings/ListingWizard";
import { PhotoManager } from "../src/listings/PhotoManager";
import { ApiError } from "../src/api/client";
import { changedFields, parseMoney, toForm } from "../src/listings/form";
import type { Listing } from "../src/listings/api";
const mocks = vi.hoisted(() => ({
  session: {
    user: {
      id: "owner",
      name: "Host",
      email: "host@example.com",
      roles: ["guest", "host"],
    } as { id: string; name: string; email: string; roles: string[] } | null,
    ready: true,
    error: null,
  },
  read: vi.fn(),
  policies: vi.fn(),
  save: vi.fn(),
  intent: vi.fn(),
  complete: vi.fn(),
  upload: vi.fn(),
  login: vi.fn(),
}));
vi.mock("../src/auth/useSession", () => ({ useSession: () => mocks.session }));
vi.mock("../src/api/client", async (original) => ({
  ...(await original<typeof import("../src/api/client")>()),
  bootstrap: vi.fn().mockResolvedValue(undefined),
  login: mocks.login,
}));
vi.mock("../src/listings/api", async (original) => ({
  ...(await original<typeof import("../src/listings/api")>()),
  listingsApi: {
    read: mocks.read,
    policies: mocks.policies,
    save: mocks.save,
    intent: mocks.intent,
    complete: mocks.complete,
  },
  uploadFile: mocks.upload,
}));
vi.mock("../src/listings/PhotoImage", () => ({
  PhotoImage: () => <div>Private photo</div>,
}));
const draft: Listing = {
  id: "draft-id",
  status: "draft",
  version: 3,
  created_at: "2026-10-30T00:00:00Z",
  updated_at: "2026-10-30T00:00:00Z",
  property_type: "house",
  address: "Old street",
  destination: "Lisbon",
  timezone: "Europe/Lisbon",
  capacity: 2,
  bedrooms: 1,
  beds: 1,
  baths: 1,
  title: "Saved title",
  description: null,
  amenities: [],
  house_rules: [],
  nightly_minor: 12905,
  cleaning_minor: 0,
  policy_id: null,
  booking_mode: "request",
  check_in_time: "15:00",
  check_out_time: "11:00",
  photos: [],
};
function wizard() {
  return (
    <MemoryRouter initialEntries={["/host/listings/draft-id/edit"]}>
      <Routes>
        <Route path="/host/listings/:id/edit" element={<ListingWizard />} />
      </Routes>
    </MemoryRouter>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.session.user = {
    id: "owner",
    name: "Host",
    email: "host@example.com",
    roles: ["guest", "host"],
  };
  mocks.read.mockResolvedValue({ listing: { ...draft } });
  mocks.policies.mockResolvedValue({ items: [] });
  mocks.save.mockImplementation(
    async (_id: string, version: number, fields: object) => ({
      listing: { ...draft, ...fields, version: version + 1 },
    }),
  );
  mocks.upload.mockResolvedValue(undefined);
});
describe("listing save and recovery", () => {
  it("preserves legacy categories and serializes explicit tag removal as an empty array", () => {
    expect(changedFields(toForm(draft), draft)).toEqual({});
    const tagged = { ...draft, categories: ["cabins", "off-grid"] };
    const form = toForm(tagged);
    form.destination = "Sintra";
    expect(changedFields(form, tagged)).toEqual({ destination: "Sintra" });
    form.categories = "";
    expect(changedFields(form, tagged)).toEqual({
      destination: "Sintra",
      categories: [],
    });
  });
  it("lets an owner save accurate category selections without changing other fields", async () => {
    mocks.read.mockResolvedValueOnce({
      listing: { ...draft, categories: ["cabins"] },
    });
    render(wizard());
    const cabins = await screen.findByRole("checkbox", { name: "Cabins" });
    expect(cabins).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Off-grid" }));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(mocks.save).toHaveBeenCalledWith("draft-id", 3, {
        categories: ["cabins", "off-grid"],
      }),
    );
    expect(screen.getByRole("checkbox", { name: "Off-grid" })).toBeChecked();
  });
  it("uses integer cents and only changed fields, rejecting lossy money", () => {
    expect(parseMoney("129.05")).toBe(12905);
    expect(parseMoney("0,10")).toBe(10);
    expect(() => parseMoney("1.234")).toThrow();
    const form = toForm(draft);
    form.nightly_minor = "130.01";
    expect(changedFields(form, draft)).toEqual({ nightly_minor: 13001 });
  });
  it("serializes save submissions and disables input until the response is saved", async () => {
    let resolve!: (value: { listing: Listing }) => void;
    mocks.save.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render(wizard());
    const input = await screen.findByLabelText("Destination");
    await userEvent.clear(input);
    await userEvent.type(input, "Goa");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Saving…" }));
    expect(mocks.save).toHaveBeenCalledTimes(1);
    expect(input).toBeDisabled();
    resolve({ listing: { ...draft, destination: "Goa", version: 4 } });
    await waitFor(() => expect(input).toBeEnabled());
    expect(screen.getByRole("status")).toHaveTextContent("All changes saved");
  });
  it("preserves entered values on stale version and rebases only changed fields with explicit consent", async () => {
    mocks.save.mockRejectedValueOnce(
      new ApiError(409, {
        code: "stale_version",
        message: "Changed in another tab.",
        field_errors: null,
        request_id: "request",
      }),
    );
    render(wizard());
    const destination = await screen.findByLabelText("Destination");
    await userEvent.clear(destination);
    await userEvent.type(destination, "Kyoto");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Changed in another tab.")).toBeVisible();
    expect(destination).toHaveValue("Kyoto");
    mocks.read.mockResolvedValueOnce({
      listing: { ...draft, address: "Updated elsewhere", version: 8 },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Load latest saved version" }),
    );
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Keep my edits on latest version",
      }),
    );
    expect(screen.getByLabelText("Street address")).toHaveValue(
      "Updated elsewhere",
    );
    expect(destination).toHaveValue("Kyoto");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(mocks.save).toHaveBeenLastCalledWith("draft-id", 8, {
      destination: "Kyoto",
    });
  });
  it("keeps an admitted editor mounted across definitive auth expiry, hides data, and recovers edits after same-account login", async () => {
    const view = render(
      <MemoryRouter initialEntries={["/host/listings/draft-id/edit"]}>
        <App />
      </MemoryRouter>,
    );
    const destination = await screen.findByLabelText("Destination");
    await userEvent.clear(destination);
    await userEvent.type(destination, "Recover this input");
    mocks.session.user = null;
    view.rerender(
      <MemoryRouter initialEntries={["/host/listings/draft-id/edit"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Sign in to continue editing" }),
    ).toBeVisible();
    expect(screen.queryByLabelText("Destination")).toBeNull();
    mocks.login.mockImplementation(async () => {
      mocks.session.user = {
        id: "owner",
        name: "Host",
        email: "host@example.com",
        roles: ["guest", "host"],
      };
    });
    await userEvent.type(
      screen.getByLabelText("Email address"),
      "host@example.com",
    );
    await userEvent.type(screen.getByLabelText("Password"), "valid-password");
    await userEvent.click(
      screen.getByRole("button", { name: "Sign in and recover edits" }),
    );
    expect(await screen.findByLabelText("Destination")).toHaveValue(
      "Recover this input",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(mocks.save).toHaveBeenCalledWith("draft-id", 3, {
      destination: "Recover this input",
    });
  });
});
describe("photo retry lifecycle", () => {
  const intent = {
    photo_id: "photo-a",
    upload: {
      method: "PUT",
      url: "http://storage/presigned",
      headers: { "Content-Type": "image/png" },
    },
    expires_in: 300,
  };
  it("retries verification with the same photo id without uploading again on transient failure", async () => {
    mocks.intent.mockResolvedValue(intent);
    mocks.complete
      .mockRejectedValueOnce(new Error("Storage unavailable"))
      .mockResolvedValueOnce({ listing: draft, photo: { id: "photo-a" } });
    render(
      <PhotoManager
        listing={draft}
        onChange={vi.fn()}
        disabled={false}
        onBusy={vi.fn()}
      />,
    );
    const file = new File(["image bytes"], "room.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Add photos"), file);
    await userEvent.click(
      await screen.findByRole("button", { name: "Retry verification" }),
    );
    await waitFor(() => expect(mocks.complete).toHaveBeenCalledTimes(2));
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.intent).toHaveBeenCalledTimes(1);
    expect(mocks.complete.mock.calls.map((call) => call[1])).toEqual([
      "photo-a",
      "photo-a",
    ]);
  });
  it("offers a new upload authorization after an expired completion instead of looping on the expired slot", async () => {
    mocks.intent
      .mockResolvedValueOnce(intent)
      .mockResolvedValueOnce({ ...intent, photo_id: "photo-b" });
    mocks.complete
      .mockRejectedValueOnce(
        new ApiError(422, {
          code: "upload_expired",
          message: "Upload expired",
          field_errors: null,
          request_id: "request",
        }),
      )
      .mockResolvedValueOnce({ listing: draft, photo: { id: "photo-b" } });
    render(
      <PhotoManager
        listing={draft}
        onChange={vi.fn()}
        disabled={false}
        onBusy={vi.fn()}
      />,
    );
    await userEvent.upload(
      screen.getByLabelText("Add photos"),
      new File(["bytes"], "room.png", { type: "image/png" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Restart photo upload" }),
    );
    await waitFor(() => expect(mocks.complete).toHaveBeenCalledTimes(2));
    expect(mocks.intent).toHaveBeenCalledTimes(2);
    expect(mocks.upload).toHaveBeenCalledTimes(2);
    expect(mocks.complete).toHaveBeenLastCalledWith("draft-id", "photo-b");
  });
});
