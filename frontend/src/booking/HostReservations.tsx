import { useEffect, useState } from "react";
import { authenticated } from "../api/client";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { TripCard } from "./Trips";
import { bookingError, type ReservationPage } from "./api";
export function HostReservations() {
  const [page, setPage] = useState<ReservationPage | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void authenticated<ReservationPage>("/host/reservations", {
      signal: controller.signal,
    })
      .then((p) => {
        if (!controller.signal.aborted) {
          setPage(p);
          setError("");
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(bookingError(e));
      });
    return () => controller.abort();
  }, [attempt]);
  async function more() {
    if (!page?.next_cursor) return;
    setBusy(true);
    try {
      const next = await authenticated<ReservationPage>(
        `/host/reservations?cursor=${page.next_cursor}`,
      );
      setPage({
        items: [...page.items, ...next.items],
        next_cursor: next.next_cursor,
      });
    } catch (e) {
      setError(bookingError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="host-content">
      <div className="page-heading">
        <h1>Reservations</h1>
        <p>Booked terms, conversations and completed-stay reviews.</p>
      </div>
      {error && (
        <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
      )}
      {!page && !error && <p role="status">Loading reservations…</p>}
      {page &&
        (page.items.length ? (
          <div className="trip-list">
            {page.items.map((r) => (
              <TripCard key={r.id} reservation={r} />
            ))}
          </div>
        ) : (
          <EmptyState title="No reservations yet">
            Your guest reservations will appear here.
          </EmptyState>
        ))}
      {page?.next_cursor && (
        <Button disabled={busy} onClick={() => void more()}>
          Load more reservations
        </Button>
      )}
    </main>
  );
}
