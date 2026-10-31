import { authenticated } from "../api/client";
export type MessagePhoto = {
  id: string;
  url: string;
  expires_at: string;
  width: number;
  height: number;
};
export type Message = {
  id: string;
  sequence: number;
  sender_id: string;
  text: string;
  created_at: string;
  attachments: MessagePhoto[];
};
export type MessagePage = {
  items: Message[];
  next_cursor: number | null;
  acknowledged_cursor: string;
  unread_count: number;
  reservation_code: string;
  listing_title: string;
};
export type Conversation = {
  reservation_id: string;
  reservation_code: string;
  listing_title: string;
  counterpart_name: string;
  unread_count: number;
  last_message_preview: string;
  updated_at: string;
};
export type InboxPage = {
  items: Conversation[];
  next_cursor: string | null;
  unread_count: number;
};
export const communicationApi = {
  inbox: (role: string, cursor?: string, signal?: AbortSignal) =>
    authenticated<InboxPage>(
      `/conversations?${new URLSearchParams({ role, ...(cursor ? { cursor } : {}) })}`,
      { signal },
    ),
  messages: (id: string, before?: number, signal?: AbortSignal) =>
    authenticated<MessagePage>(
      `/reservations/${id}/messages${before ? `?before=${before}` : ""}`,
      { signal },
    ),
  read: (id: string, acknowledged_cursor: string) =>
    authenticated<{ unread_count: number }>(
      `/reservations/${id}/messages/read`,
      { method: "POST", body: JSON.stringify({ acknowledged_cursor }) },
    ),
  send: (id: string, text: string, attachment_ids: string[], key: string) =>
    authenticated<{ message: Message }>(`/reservations/${id}/messages`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ text, attachment_ids }),
    }),
  uploadIntent: (id: string, file: File) =>
    authenticated<{ attachment_id: string; upload_url: string }>(
      `/reservations/${id}/messages/attachments`,
      {
        method: "POST",
        body: JSON.stringify({ content_type: file.type, bytes: file.size }),
      },
    ),
  complete: (id: string, photo: string) =>
    authenticated<MessagePhoto>(
      `/reservations/${id}/messages/attachments/${photo}/complete`,
      { method: "POST", body: "{}" },
    ),
};
