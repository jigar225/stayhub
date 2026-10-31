import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useBusinessTime } from "../api/businessTime";
import { arrivingToday, arrivalTime } from "./arrivals";
import { ApiError } from "../api/client";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { formatDate } from "../discovery/dates";
import { formatEUR } from "../listings/form";
import {
  bookingApi,
  bookingError,
  type Reservation,
  type TodayData,
} from "./api";
import { Status } from "./Trips";
function RequestCard({
  reservation: r,
  onUpdated,
}: {
  reservation: Reservation;
  onUpdated: (notice: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [declining, setDeclining] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState<{
    decision: "accept" | "decline";
    key: string;
    reason?: string;
  } | null>(null);
  const flight = useRef(false);
  async function decide(decision: "accept" | "decline") {
    if (flight.current) return;
    if (
      decision === "decline" &&
      !uncertain &&
      (!reason.trim() || reason.trim().length > 500)
    ) {
      setError("Enter a decline reason of 1–500 characters.");
      return;
    }
    const submission = uncertain ?? {
      decision,
      key: crypto.randomUUID(),
      ...(decision === "decline" ? { reason: reason.trim() } : {}),
    };
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      await bookingApi.decide(
        r.id,
        submission.decision,
        submission.key,
        submission.reason,
      );
      setUncertain(null);
      onUpdated(
        submission.decision === "accept"
          ? "Request accepted. The existing charge is retained; no additional charge was made."
          : "Request declined. The full simulated payment was refunded and the dates are available again.",
      );
    } catch (e) {
      const unknown =
        !(e instanceof ApiError) ||
        e.status >= 500 ||
        e.details.code === "operation_in_progress";
      setUncertain(unknown ? submission : null);
      setError(bookingError(e));
      if (
        e instanceof ApiError &&
        ["request_expired", "invalid_state"].includes(e.details.code)
      )
        onUpdated(bookingError(e));
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  return (
    <article className="card request-card">
      <Status reservation={r} />
      <h3>{r.listing_snapshot.title}</h3>
      <p>
        {formatDate(r.check_in)} – {formatDate(r.check_out)} · {r.guests} guests
      </p>
      <p>
        Reservation <code>{r.code}</code> · {formatEUR(r.price.total_minor)}{" "}
        charged
      </p>
      <p className="deadline-notice">
        Respond before{" "}
        {r.request_deadline &&
          new Intl.DateTimeFormat("en-GB", {
            dateStyle: "medium",
            timeStyle: "short",
            timeZone: r.timezone,
          }).format(new Date(r.request_deadline))}{" "}
        ({r.timezone})
      </p>
      <Link to={`/trips/${r.id}`}>View booked terms</Link>
      {error && <ErrorState message={error} />}
      {uncertain ? (
        <Button disabled={busy} onClick={() => void decide(uncertain.decision)}>
          {busy ? "Resolving…" : "Retry original decision"}
        </Button>
      ) : declining ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void decide("decline");
          }}
        >
          <label>
            Decline reason
            <textarea
              value={reason}
              maxLength={500}
              disabled={busy}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <p className="field-help">
            Declining refunds the full simulated payment and releases the dates.
          </p>
          <div className="decision-actions">
            <Button variant="danger" disabled={busy}>
              {busy ? "Declining…" : "Confirm decline"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => setDeclining(false)}
            >
              Keep request
            </Button>
          </div>
        </form>
      ) : (
        <div className="decision-actions">
          <Button disabled={busy} onClick={() => void decide("accept")}>
            {busy ? "Accepting…" : "Accept request"}
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => setDeclining(true)}
          >
            Decline request
          </Button>
        </div>
      )}
    </article>
  );
}
export function HostToday() {
  const clock = useBusinessTime();
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("Requests");
  const [notice, setNotice] = useState("");
  const generation = useRef<{ active: boolean } | null>(null);
  useEffect(() => {
    const request = { active: true };
    generation.current = request;
    void bookingApi
      .today()
      .then((result) => {
        if (request.active) {
          setBusy(false);
          setData(result);
          setError("");
        }
      })
      .catch((e) => {
        if (request.active) {
          setBusy(false);
          setData(null);
          setError(bookingError(e));
        }
      });
    return () => {
      request.active = false;
    };
  }, [attempt]);
  async function more() {
    if (!data?.next_cursor || busy) return;
    const request = generation.current;
    setBusy(true);
    setError("");
    try {
      const next = await bookingApi.today(data.next_cursor);
      if (!request?.active) return;
      setData({
        ...next,
        pending: [...data.pending, ...next.pending],
        upcoming: [...data.upcoming, ...next.upcoming],
        hosting: [...data.hosting, ...next.hosting],
        checkouts: [...data.checkouts, ...next.checkouts],
      });
    } catch (e) {
      if (request?.active) setError(bookingError(e));
    } finally {
      if (request?.active) setBusy(false);
    }
  }
  const arrivals =
    clock.now && !clock.error
      ? arrivingToday(data?.upcoming ?? [], clock.now)
      : null;
  const shown =
    tab === "Arriving today"
      ? (arrivals ?? [])
      : tab === "Upcoming"
        ? (data?.upcoming ?? [])
        : tab === "Currently hosting"
          ? (data?.hosting ?? [])
          : (data?.checkouts ?? []);
  return (
    <main className="host-content">
      <div className="page-heading">
        <h1>Today</h1>
        <p>
          Review requests, upcoming stays and stay progress. Counts show loaded
          records, not global totals.
        </p>
      </div>
      {error && (
        <ErrorState
          message={error}
          retry={() =>
            data?.next_cursor ? void more() : setAttempt(attempt + 1)
          }
        />
      )}
      {notice && (
        <p className="calendar-notice" role="status">
          {notice}
        </p>
      )}
      {!data && !error ? (
        <p role="status">Loading your workspace…</p>
      ) : (
        data && (
          <>
            {data.pending.length > 0 && (
              <div className="deadline-notice">
                {data.pending.length} requests on this page need a response
                before their deadlines. Unanswered requests expire with a full
                refund.
              </div>
            )}
            <section
              className="host-arrivals-summary"
              aria-label="Today's arrivals"
            >
              <div>
                <h2>Arriving today</h2>
                <p>
                  {arrivals
                    ? `${arrivals.length} confirmed ${arrivals.length === 1 ? "stay" : "stays"} in the loaded reservations. Dates use each stay’s local timezone.`
                    : "Checking the business date for arrivals…"}
                </p>
              </div>
              {clock.error ? (
                <div>
                  <p role="status">
                    Could not check today’s arrivals. Other reservations remain
                    available.
                  </p>
                  <Button
                    variant="secondary"
                    onClick={() => void clock.refresh()}
                  >
                    Retry arrivals date
                  </Button>
                </div>
              ) : (
                <Button
                  variant="secondary"
                  disabled={!arrivals}
                  onClick={() => setTab("Arriving today")}
                >
                  View arrivals
                </Button>
              )}
            </section>
            <nav className="trip-tabs" aria-label="Reservation categories">
              {[
                "Requests",
                "Arriving today",
                "Upcoming",
                "Currently hosting",
                "Checking out",
              ].map((value) => (
                <Button
                  key={value}
                  variant={tab === value ? "primary" : "secondary"}
                  onClick={() => setTab(value)}
                >
                  {value}
                  {value === "Requests"
                    ? ` (${data.pending.length} loaded)`
                    : value === "Arriving today"
                      ? arrivals
                        ? ` (${arrivals.length} loaded)`
                        : " (date unavailable)"
                      : value === "Upcoming"
                        ? ` (${data.upcoming.length} loaded)`
                        : value === "Currently hosting"
                          ? ` (${data.hosting.length} loaded)`
                          : ` (${data.checkouts.length} loaded)`}
                </Button>
              ))}
            </nav>
            {tab === "Requests" ? (
              data.pending.length ? (
                <div className="request-grid">
                  {data.pending.map((r) => (
                    <RequestCard
                      key={r.id}
                      reservation={r}
                      onUpdated={(message) => {
                        setNotice(message);
                        setAttempt(attempt + 1);
                      }}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No pending requests"
                  action={
                    <Link to="/host/listings" className="button secondary">
                      Manage listings
                    </Link>
                  }
                >
                  New guest requests will appear here when someone books a
                  request stay.
                </EmptyState>
              )
            ) : tab === "Arriving today" && !arrivals ? (
              <p role="status">
                Arrivals need a current business date. Use Retry arrivals date
                if the clock is unavailable.
              </p>
            ) : shown.length ? (
              <div className="trip-list">
                {shown.map((r) => (
                  <article className="card trip-card" key={r.id}>
                    <div>
                      <Status reservation={r} />
                      <h2>{r.listing_snapshot.title}</h2>
                      <p>
                        {formatDate(r.check_in)} – {formatDate(r.check_out)} ·{" "}
                        {r.guests} guests
                      </p>
                      <p className="host-arrival-time">
                        {tab === "Arriving today"
                          ? "Arriving today · "
                          : "Check-in · "}
                        {arrivalTime(r)} ({r.timezone})
                      </p>
                      <code>{r.code}</code>
                    </div>
                    <Link className="button secondary" to={`/trips/${r.id}`}>
                      View reservation
                    </Link>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState title={`No ${tab.toLowerCase()} stays`}>
                No matching stays in the loaded page. Load more reservations if
                available.
              </EmptyState>
            )}
            {data.next_cursor && (
              <Button disabled={busy} onClick={() => void more()}>
                {busy ? "Loading…" : "Load more reservations"}
              </Button>
            )}
          </>
        )
      )}
    </main>
  );
}
