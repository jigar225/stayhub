import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Messages } from "../src/communication/Messages";
import { ApiError } from "../src/api/client";
const mocks = vi.hoisted(() => ({
  messages: vi.fn(),
  read: vi.fn(),
  send: vi.fn(),
  uploadIntent: vi.fn(),
  complete: vi.fn(),
  user: { id: "guest", roles: ["guest"], name: "Guest" },
}));
vi.mock("../src/auth/useSession", () => ({
  useSession: () => ({ user: mocks.user }),
}));
vi.mock("../src/communication/api", () => ({
  communicationApi: {
    messages: mocks.messages,
    read: mocks.read,
    send: mocks.send,
    uploadIntent: mocks.uploadIntent,
    complete: mocks.complete,
  },
}));
function mount() {
  return render(
    <MemoryRouter initialEntries={["/messages/reservation-one"]}>
      <Routes>
        <Route path="/messages/:reservationId" element={<Messages />} />
      </Routes>
    </MemoryRouter>,
  );
}
const message = {
  id: "message-one",
  sequence: 1,
  sender_id: "host",
  text: "<script>danger()</script>",
  created_at: "2026-10-31T10:00:00Z",
  attachments: [],
};
beforeEach(() => {
  mocks.messages.mockReset();
  mocks.read.mockReset();
  mocks.send.mockReset();
  mocks.uploadIntent.mockReset();
  mocks.complete.mockReset();
  mocks.messages.mockResolvedValue({
    items: [message],
    next_cursor: null,
    acknowledged_cursor: "loaded-only-cursor",
    unread_count: 1,
    reservation_code: "SH-TEST",
    listing_title: "Private stay",
  });
  mocks.read.mockResolvedValue({ unread_count: 0 });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("renders untrusted text safely and acknowledges only the returned loaded cursor", async () => {
  mount();
  await screen.findByText(message.text);
  expect(document.querySelector("script")).toBeNull();
  await waitFor(() =>
    expect(mocks.read).toHaveBeenCalledWith(
      "reservation-one",
      "loaded-only-cursor",
    ),
  );
});
it("uncertain sends retain their original key and payload for a duplicate-free retry", async () => {
  mocks.send
    .mockRejectedValueOnce(new Error("Dropped response"))
    .mockResolvedValueOnce({
      message: {
        ...message,
        id: "sent",
        sender_id: "guest",
        sequence: 2,
        text: "Hello host",
      },
    });
  mount();
  await screen.findByText(message.text);
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Hello host" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByRole("button", { name: "Retry same message" });
  const original = mocks.send.mock.calls[0];
  fireEvent.click(screen.getByRole("button", { name: "Retry same message" }));
  await screen.findByText("Hello host");
  expect(mocks.send.mock.calls[1]).toEqual(original);
  expect(mocks.send).toHaveBeenCalledTimes(2);
});
it("does not fetch while the tab is hidden and releases polling on unmount", async () => {
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  const clear = vi.spyOn(window, "clearInterval");
  const view = mount();
  expect(mocks.messages).not.toHaveBeenCalled();
  view.unmount();
  expect(clear).toHaveBeenCalled();
});

it("recovers a gap introduced by more than one page arriving between polls", async () => {
  const messages = (start: number, end: number) =>
    Array.from({ length: end - start + 1 }, (_, n) => ({
      ...message,
      id: `message-${start + n}`,
      sequence: start + n,
      text: `Arrival message ${start + n}`,
    }));
  const response = (start: number, end: number, next: number | null) => ({
    items: messages(start, end),
    next_cursor: next,
    acknowledged_cursor: `loaded-${start}-${end}`,
    unread_count: 0,
    reservation_code: "SH-TEST",
    listing_title: "Private stay",
  });
  mocks.messages
    .mockResolvedValueOnce(response(1, 30, null))
    .mockResolvedValueOnce(response(36, 65, 36))
    .mockResolvedValueOnce(response(6, 35, 6))
    .mockResolvedValue(response(36, 65, 36));
  mount();
  await screen.findByText("Arrival message 30");
  expect(
    screen.queryByRole("button", { name: "Load earlier messages" }),
  ).toBeNull();
  fireEvent(document, new Event("visibilitychange"));
  await screen.findByText("Arrival message 65");
  expect(screen.queryByText("Arrival message 31")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Load earlier messages" }),
  );
  await screen.findByText("Arrival message 31");
  expect(mocks.messages).toHaveBeenNthCalledWith(3, "reservation-one", 36);
  for (let n = 1; n <= 65; n++)
    expect(
      screen.getByText(`Arrival message ${n}`, { exact: true }),
    ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Load earlier messages" }),
  ).toBeNull();
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() => expect(mocks.messages).toHaveBeenCalledTimes(4));
  expect(
    screen.queryByRole("button", { name: "Load earlier messages" }),
  ).toBeNull();
});
it("definitive attachment rejection lets the guest remove photos and edit a new message", async () => {
  const photo = {
    id: "expired-photo",
    url: "/private-photo",
    width: 80,
    height: 60,
    expires_at: "2026-10-31T10:05:00Z",
  };
  mocks.uploadIntent.mockResolvedValue({
    attachment_id: photo.id,
    upload_url: "/upload",
  });
  mocks.complete.mockResolvedValue(photo);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  mocks.send
    .mockRejectedValueOnce(
      new ApiError(422, {
        code: "attachment_invalid",
        message: "Photo expired. Remove it and attach it again.",
        field_errors: null,
        request_id: "fixture",
      }),
    )
    .mockResolvedValueOnce({
      message: {
        ...message,
        id: "corrected",
        sender_id: "guest",
        sequence: 2,
        text: "Corrected arrival details",
      },
    });
  const view = mount();
  await screen.findByText(message.text);
  const input = view.container.querySelector('input[type="file"]')!;
  fireEvent.change(input, {
    target: {
      files: [new File(["photo"], "arrival.png", { type: "image/png" })],
    },
  });
  await screen.findByAltText("Photo ready to attach");
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Original details" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByText("Photo expired. Remove it and attach it again.");
  expect(
    screen.queryByRole("button", { name: "Retry same message" }),
  ).toBeNull();
  expect(
    (screen.getByLabelText("Message") as HTMLTextAreaElement).disabled,
  ).toBe(false);
  const originalKey = mocks.send.mock.calls[0][3];
  fireEvent.click(screen.getByRole("button", { name: "Remove photo" }));
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Corrected arrival details" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByText("Corrected arrival details");
  expect(mocks.send.mock.calls[1][1]).toBe("Corrected arrival details");
  expect(mocks.send.mock.calls[1][2]).toEqual([]);
  expect(mocks.send.mock.calls[1][3]).not.toBe(originalKey);
});
