import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useSession } from "../auth/useSession";
import { ApiError } from "../api/client";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { bookingError } from "../booking/api";
import {
  communicationApi,
  type InboxPage,
  type Message,
  type MessagePage,
  type MessagePhoto,
} from "./api";

function mergeMessages(previous: Message[], incoming: Message[]) {
  const merged = new Map(previous.map((m) => [m.id, m]));
  incoming.forEach((m) => merged.set(m.id, m));
  return [...merged.values()].sort((a, b) => a.sequence - b.sequence);
}
function nextHistoryCursor(items: Message[], earlier: number | null) {
  for (let n = items.length - 1; n > 0; n--)
    if (items[n].sequence > items[n - 1].sequence + 1) return items[n].sequence;
  return earlier;
}
function InboxContent() {
  const { user } = useSession();
  const [query] = useSearchParams();
  const role = query.get("role") === "host" ? "host" : "guest";
  const [page, setPage] = useState<InboxPage | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!user) return;
    let active = true,
      flight = false;
    const controller = new AbortController();
    async function load() {
      if (document.hidden || flight) return;
      flight = true;
      try {
        const result = await communicationApi.inbox(
          role,
          undefined,
          controller.signal,
        );
        if (active) {
          setPage(result);
          setError("");
        }
      } catch (e) {
        if (active) setError(bookingError(e));
      } finally {
        flight = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    document.addEventListener("visibilitychange", load);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, [user, role, attempt]);
  async function more() {
    if (!page?.next_cursor || busy) return;
    setBusy(true);
    try {
      const result = await communicationApi.inbox(role, page.next_cursor);
      setPage((previous) =>
        previous
          ? { ...result, items: [...previous.items, ...result.items] }
          : result,
      );
    } catch (e) {
      setError(bookingError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="page communication-page">
      <div className="page-heading">
        <h1>Messages</h1>
        <p>Keep your reservation conversations together.</p>
      </div>
      <nav className="tabs" aria-label="Inbox role">
        <Link
          aria-current={role === "guest" ? "page" : undefined}
          to="/messages?role=guest"
        >
          Traveling
        </Link>
        {user?.roles.includes("host") && (
          <Link
            aria-current={role === "host" ? "page" : undefined}
            to="/messages?role=host"
          >
            Hosting
          </Link>
        )}
      </nav>
      <p className="communication-warning">
        Protect your booking: never pay or share payment details outside
        StayHub.
      </p>
      {error && (
        <ErrorState message={error} retry={() => setAttempt((n) => n + 1)} />
      )}
      {!page && !error && <p role="status">Loading conversations…</p>}
      {page && (
        <>
          <p role="status">{page.unread_count} unread messages</p>
          {!page.items.length ? (
            <EmptyState title="No conversations yet">
              Open a reservation to message your guest or host.
            </EmptyState>
          ) : (
            <div className="conversation-list">
              {page.items.map((c) => (
                <Link
                  className="card conversation-card"
                  key={c.reservation_id}
                  to={`/messages/${c.reservation_id}?role=${role}`}
                >
                  <div>
                    <h2>{c.counterpart_name}</h2>
                    <strong>{c.listing_title}</strong>
                    <p>{c.reservation_code}</p>
                    <p className="message-preview">{c.last_message_preview}</p>
                  </div>
                  <span>
                    {c.unread_count ? `${c.unread_count} unread` : "Read"}
                  </span>
                </Link>
              ))}
            </div>
          )}
          {page.next_cursor && (
            <Button
              disabled={busy}
              variant="secondary"
              onClick={() => void more()}
            >
              Load more conversations
            </Button>
          )}
        </>
      )}
    </main>
  );
}
function ConversationMessages() {
  const params = useParams();
  const id = params.reservationId ?? params.id ?? "";
  const { user } = useSession();
  const [query] = useSearchParams();
  const role = query.get("role") === "host" ? "host" : "guest";
  const [page, setPage] = useState<MessagePage | null>(null);
  const [items, setItems] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [text, setText] = useState("");
  const photoInput = useRef<HTMLInputElement>(null);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const input = messageInput.current;
    if (input) {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    }
  }, [text, page]);
  const [photos, setPhotos] = useState<MessagePhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [olderBusy, setOlderBusy] = useState(false);
  const [uncertain, setUncertain] = useState<{
    text: string;
    ids: string[];
    key: string;
  } | null>(null);
  const flight = useRef(false);
  const loadedHistory = useRef<{ items: Message[]; earlier: number | null }>({
    items: [],
    earlier: null,
  });
  const acknowledged = useRef(new Set<string>());
  const actorId = user?.id;
  useEffect(() => {
    if (!actorId || !id) return;
    let active = true,
      loading = false;
    const controller = new AbortController();
    async function load() {
      if (document.hidden || loading) return;
      loading = true;
      try {
        const result = await communicationApi.messages(
          id,
          undefined,
          controller.signal,
        );
        if (active) {
          const previous = loadedHistory.current;
          if (
            !previous.items.length ||
            (result.items[0] &&
              result.items[0].sequence < previous.items[0].sequence)
          )
            previous.earlier = result.next_cursor;
          previous.items = mergeMessages(previous.items, result.items);
          setItems(previous.items);
          setPage({
            ...result,
            next_cursor: nextHistoryCursor(previous.items, previous.earlier),
          });
          setError("");
        }
      } catch (e) {
        if (active) setError(bookingError(e));
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 5000);
    document.addEventListener("visibilitychange", load);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, [actorId, id, attempt]);
  useEffect(() => {
    if (!page || !actorId || document.hidden) return;
    const incoming = page.items
      .filter((m) => m.sender_id !== actorId)
      .map((m) => m.id)
      .join(",");
    if (!incoming || acknowledged.current.has(incoming)) return;
    acknowledged.current.add(incoming);
    void communicationApi.read(id, page.acknowledged_cursor).catch(() => {
      acknowledged.current.delete(incoming);
    });
  }, [page, actorId, id]);
  async function older() {
    if (!page?.next_cursor || olderBusy) return;
    setOlderBusy(true);
    try {
      const result = await communicationApi.messages(id, page.next_cursor);
      const previous = loadedHistory.current;
      if (
        !previous.items.length ||
        (result.items[0] &&
          result.items[0].sequence < previous.items[0].sequence)
      )
        previous.earlier = result.next_cursor;
      previous.items = mergeMessages(previous.items, result.items);
      setItems(previous.items);
      setPage((prev) =>
        prev
          ? {
              ...prev,
              next_cursor: nextHistoryCursor(previous.items, previous.earlier),
            }
          : prev,
      );
      await communicationApi.read(id, result.acknowledged_cursor);
    } catch (e) {
      setError(bookingError(e));
    } finally {
      setOlderBusy(false);
    }
  }
  async function upload(file: File | undefined) {
    if (!file) return;
    if (
      !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
      file.size > 10 * 1024 * 1024 ||
      photos.length >= 3
    ) {
      setError(
        "Choose up to3 JPEG, PNG or WebP photos, each no larger than10 MiB.",
      );
      return;
    }
    setUploading(true);
    setError("");
    try {
      const intent = await communicationApi.uploadIntent(id, file);
      const response = await fetch(intent.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
        signal: AbortSignal.timeout(30000),
      });
      if (!response.ok)
        throw new Error("Photo upload failed. Select the photo to retry.");
      const photo = await communicationApi.complete(id, intent.attachment_id);
      setPhotos((prev) => [...prev, photo]);
    } catch (e) {
      setError(bookingError(e));
    } finally {
      setUploading(false);
    }
  }
  async function send() {
    if (flight.current || uploading) return;
    const submission = uncertain ?? {
      text: text.trim(),
      ids: photos.map((p) => p.id),
      key: crypto.randomUUID(),
    };
    if (!submission.text && !submission.ids.length) {
      setError("Write a message or attach a photo.");
      return;
    }
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await communicationApi.send(
        id,
        submission.text,
        submission.ids,
        submission.key,
      );
      const previous = loadedHistory.current;
      if (!previous.items.length && result.message.sequence > 1)
        previous.earlier = result.message.sequence;
      previous.items = mergeMessages(previous.items, [result.message]);
      setItems(previous.items);
      setPage((prev) =>
        prev
          ? {
              ...prev,
              next_cursor: nextHistoryCursor(previous.items, previous.earlier),
            }
          : prev,
      );
      setUncertain(null);
      setText("");
      setPhotos([]);
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status >= 400 &&
        e.status < 500 &&
        ![401, 408].includes(e.status)
      ) {
        setUncertain(null);
        setError(bookingError(e));
      } else {
        setUncertain(submission);
        setError(`${bookingError(e)} Retry the same send to avoid duplicates.`);
      }
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  return (
    <main className="page communication-page conversation-page">
      <Link to={`/messages?role=${role}`}>← All messages</Link>
      <div className="page-heading">
        <h1>{page?.listing_title ?? "Reservation messages"}</h1>
        {page && <p>Reservation {page.reservation_code}</p>}
      </div>
      <p className="communication-warning">
        Protect your booking: never pay or share payment details outside
        StayHub.
      </p>
      {error && (
        <ErrorState message={error} retry={() => setAttempt((n) => n + 1)} />
      )}
      {!page && !error && <p role="status">Loading messages…</p>}
      {page && (
        <>
          <div className="message-history" aria-label="Conversation history">
            {page.next_cursor && (
              <Button
                disabled={olderBusy}
                variant="secondary"
                onClick={() => void older()}
              >
                {olderBusy ? "Loading…" : "Load earlier messages"}
              </Button>
            )}
            {!items.length && (
              <EmptyState title="Start the conversation">
                Ask a question or share arrival details with your guest or host.
              </EmptyState>
            )}
            {items.map((m) => (
              <article
                key={m.id}
                className={`message-bubble ${m.sender_id === actorId ? "outgoing" : "incoming"}`}
              >
                <p className="message-author">
                  {m.sender_id === actorId ? "You" : "Your guest or host"}
                </p>
                {m.text && <p className="message-text">{m.text}</p>}
                {m.attachments.map((p) => (
                  <a key={p.id} href={p.url} target="_blank" rel="noreferrer">
                    <img
                      className="message-photo"
                      src={p.url}
                      width={p.width}
                      height={p.height}
                      alt="Private reservation attachment"
                    />
                  </a>
                ))}
                <time dateTime={m.created_at}>
                  {new Date(m.created_at).toLocaleString()}
                </time>
              </article>
            ))}
          </div>
          <form
            className="message-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <div className="message-attachments">
              {photos.map((p) => (
                <div key={p.id}>
                  <img
                    src={p.url}
                    alt="Photo ready to attach"
                    width={80}
                    height={80}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy || !!uncertain}
                    onClick={() =>
                      setPhotos((prev) => prev.filter((a) => a.id !== p.id))
                    }
                  >
                    Remove photo
                  </Button>
                </div>
              ))}
            </div>
            <div className="message-composer-field">
              <input
                ref={photoInput}
                className="message-file-input"
                aria-label="Attach photo"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                disabled={
                  uploading || busy || photos.length >= 3 || !!uncertain
                }
                onChange={(e) => {
                  void upload(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                className="composer-icon composer-attach"
                aria-label="Add photo"
                title="Attach photo (up to 3, 10 MiB each)"
                disabled={
                  uploading || busy || photos.length >= 3 || !!uncertain
                }
                onClick={() => photoInput.current?.click()}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  aria-hidden="true"
                >
                  <path
                    d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l8-8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              <textarea
                ref={messageInput}
                id="message-text"
                aria-label="Message"
                aria-describedby="message-composer-help"
                placeholder="Write a message…"
                maxLength={4000}
                rows={1}
                value={text}
                disabled={busy || !!uncertain}
                onChange={(e) => setText(e.target.value)}
              />
              <button
                className="composer-icon composer-send"
                disabled={busy || uploading}
                type="submit"
                aria-label={
                  busy
                    ? "Sending…"
                    : uncertain
                      ? "Retry same message"
                      : "Send message"
                }
                title={uncertain ? "Retry same message" : "Send message"}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <path
                    d="M12 19V5m-6 6 6-6 6 6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
            <p id="message-composer-help" className="composer-help">
              {uploading
                ? "Verifying photo…"
                : busy
                  ? "Sending…"
                  : "Up to 3 photos · 10 MiB each"}
              <span>{text.length.toLocaleString()} / 4,000</span>
            </p>
            {uncertain && (
              <p role="status">
                Your send outcome is uncertain. Retry uses the same message key
                and cannot create a duplicate.
              </p>
            )}
          </form>
        </>
      )}
    </main>
  );
}

export function Inbox() {
  const { user } = useSession();
  const [query] = useSearchParams();
  return (
    <InboxContent key={`${user?.id ?? "anonymous"}:${query.get("role")}`} />
  );
}
export function Messages() {
  const { user } = useSession();
  const params = useParams();
  return (
    <ConversationMessages
      key={`${user?.id ?? "anonymous"}:${params.reservationId ?? params.id}`}
    />
  );
}
