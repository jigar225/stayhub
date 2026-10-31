import { useEffect, useState } from "react";
import { Link } from "react-router";
import { authenticated } from "../api/client";
import { useSession } from "../auth/useSession";
import { Button, EmptyState, ErrorState } from "../components/ui";

type Notice = {
  id: number;
  kind: string;
  title: string;
  href: string;
  created_at: string;
  read_at: string | null;
};
type Page = {
  items: Notice[];
  next_cursor: number | null;
  unread_count: number;
  cutoff: number;
};
const load = (before?: number, signal?: AbortSignal) =>
  authenticated<Page>(`/me/notifications${before ? `?before=${before}` : ""}`, {
    signal,
  });
const read = (id: number) =>
  authenticated(`/me/notifications/${id}/read`, { method: "POST", body: "{}" });

export function NotificationBell() {
  const { user } = useSession();
  const actorId = user?.id;
  const [count, setCount] = useState<{ actor: string; value: number } | null>(
    null,
  );
  useEffect(() => {
    if (!actorId) return;
    let active = true;
    let running = false;
    const controller = new AbortController();
    const refresh = async () => {
      if (document.hidden || !active || running) return;
      running = true;
      try {
        const page = await load(undefined, controller.signal);
        if (active) setCount({ actor: actorId, value: page.unread_count });
      } catch {
        /* The full list provides an actionable error/retry state. */
      } finally {
        running = false;
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("stayhub-notifications-read", refresh);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("stayhub-notifications-read", refresh);
    };
  }, [actorId]);
  if (!user) return null;
  const n = count?.actor === user.id ? count.value : 0;
  return (
    <Link
      to="/notifications"
      className="notification-bell"
      aria-label={`Notifications${n ? `, ${n} unread` : ""}`}
    >
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        aria-hidden="true"
      >
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
      </svg>
      {n > 0 && <span>{n > 99 ? "99+" : n}</span>}
    </Link>
  );
}

export function Notifications() {
  const { user } = useSession();
  const [data, setData] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void load(undefined, controller.signal)
      .then((p) => {
        if (active) {
          setData(p);
          setError("");
        }
      })
      .catch((e: unknown) => {
        if (active)
          setError(
            e instanceof Error ? e.message : "Unable to load notifications.",
          );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [user?.id, attempt]);
  async function acknowledge(id?: number) {
    if (!data || busy) return;
    setBusy(true);
    setError("");
    try {
      if (id) await read(id);
      else
        await authenticated("/me/notifications/read-all", {
          method: "POST",
          body: JSON.stringify({ cutoff: data.cutoff }),
        });
      // Reload after the cutoff-based acknowledgement: arrivals after that
      // cutoff remain unread and must also appear in the visible list/count.
      setData(await load());
      window.dispatchEvent(new Event("stayhub-notifications-read"));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unable to mark notifications read.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function more() {
    if (!data?.next_cursor || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await load(data.next_cursor);
      setData({
        ...next,
        cutoff: data.cutoff,
        items: [...data.items, ...next.items],
      });
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unable to load notifications.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="page-container notifications-page">
      <div className="page-heading">
        <h1>Notifications</h1>
        <p>Reservation updates, messages and reviews.</p>
      </div>
      {error && (
        <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
      )}
      {!data && !error && <p role="status">Loading notifications…</p>}
      {data && (
        <>
          <div className="notification-toolbar">
            <p>{data.unread_count} unread</p>
            <Button
              variant="secondary"
              disabled={busy || !data.unread_count}
              onClick={() => void acknowledge()}
            >
              Mark all read
            </Button>
          </div>
          {!data.items.length ? (
            <EmptyState title="You’re all caught up">
              Your reservation updates will appear here.
            </EmptyState>
          ) : (
            <ul className="notification-list">
              {data.items.map((n) => (
                <li key={n.id} className={n.read_at ? "read" : "unread"}>
                  <div>
                    <Link
                      to={n.href}
                      onClick={() => {
                        if (!n.read_at)
                          void read(n.id)
                            .then(() =>
                              window.dispatchEvent(
                                new Event("stayhub-notifications-read"),
                              ),
                            )
                            .catch(() => {});
                      }}
                    >
                      {n.title}
                    </Link>
                    <time dateTime={n.created_at}>
                      {new Date(n.created_at).toLocaleString()}
                    </time>
                  </div>
                  {!n.read_at && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void acknowledge(n.id)}
                      aria-label={`Mark read: ${n.title}`}
                    >
                      Mark read
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {data.next_cursor && (
            <Button disabled={busy} onClick={() => void more()}>
              {busy ? "Loading…" : "Load more notifications"}
            </Button>
          )}
        </>
      )}
    </main>
  );
}
