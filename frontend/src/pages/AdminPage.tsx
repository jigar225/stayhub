import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useSession } from "../auth/useSession";
import { readAction, saveAction, clearAction } from "../booking/actionRecovery";
import { ApiError } from "../api/client";
import { refreshBusinessTime } from "../api/businessTime";
import { Brand, Button, EmptyState, ErrorState } from "../components/ui";
import { bookingError } from "../booking/api";
import {
  adminApi,
  type Clock,
  type SweepResult,
  type AuditEvent,
} from "../admin/api";
function DemoClock() {
  const { user } = useSession();
  const [clock, setClock] = useState<Clock | null>(null);
  const [seconds, setSeconds] = useState("86400");
  const [confirm, setConfirm] = useState(false);
  const [original, setOriginal] = useState<{
    seconds: number;
    key: string;
  } | null>(() => (user ? readAction("advance", user.id) : null));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<SweepResult | null>(null);
  const flight = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void adminApi
      .clock()
      .then((value) => {
        if (active) {
          setClock(value);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(bookingError(e));
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  function review() {
    if (
      !/^\d+$/.test(seconds) ||
      Number(seconds) < 1 ||
      Number(seconds) > 31536000
    ) {
      setError("Choose a whole number of seconds from 1 to 31,536,000.");
      return;
    }
    setError("");
    setConfirm(true);
  }
  async function advance() {
    if (flight.current) return;
    const payload = original ?? {
      seconds: Number(seconds),
      key: crypto.randomUUID(),
    };
    if (!user) return;
    try {
      saveAction("advance", user.id, payload);
    } catch {
      setError("Enable session storage before advancing the global clock.");
      return;
    }
    setOriginal(payload);
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      const value = await adminApi.advance(payload.seconds, payload.key);
      if (!alive.current) return;
      clearAction("advance");
      setClock(value.clock);
      setResult(value.sweep);
      setConfirm(false);
      setOriginal(null);
      await refreshBusinessTime();
      setAttempt((a) => a + 1);
    } catch (e) {
      if (!alive.current) return;
      const unknown =
        !(e instanceof ApiError) ||
        e.status >= 500 ||
        e.status === 401 ||
        e.details.code === "operation_in_progress";
      if (!unknown) {
        clearAction("advance");
        setOriginal(null);
      }
      setError(
        bookingError(e) +
          (unknown
            ? " Retry this original advance to resolve its outcome without advancing twice."
            : ""),
      );
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  async function sweep() {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      const value = await adminApi.sweep();
      setResult(value.sweep);
      await refreshBusinessTime();
      setAttempt((a) => a + 1);
    } catch (e) {
      setError(bookingError(e));
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="card demo-clock" id="demo-clock">
      <h2>Global demo clock</h2>
      <p>
        Advancing this clock affects every booking in this environment. It can
        expire requests, start and complete stays, and release simulated host
        payments. It cannot move backwards.
      </p>
      {error && (
        <ErrorState
          message={error}
          retry={!original ? () => setAttempt(attempt + 1) : undefined}
        />
      )}
      {!clock && !error ? (
        <p role="status">Loading clock…</p>
      ) : (
        clock && (
          <>
            <dl className="trip-facts">
              <div>
                <dt>Business time (UTC)</dt>
                <dd>{new Date(clock.business_now).toISOString()}</dd>
              </div>
              <div>
                <dt>Real time (UTC)</dt>
                <dd>{new Date(clock.real_now).toISOString()}</dd>
              </div>
              <div>
                <dt>Persisted advance</dt>
                <dd>
                  {clock.offset_seconds.toLocaleString("en-GB")} seconds ·
                  version {clock.version}
                </dd>
              </div>
            </dl>
            {!clock.demo_mode ? (
              <p className="deadline-notice">
                Demo advancement is disabled in this environment.
              </p>
            ) : confirm || original ? (
              <div className="deadline-notice">
                <h3>Confirm global clock advance</h3>
                <p>
                  Advance every booking by{" "}
                  {(original?.seconds ?? Number(seconds)).toLocaleString(
                    "en-GB",
                  )}{" "}
                  seconds? All due changes will be processed. This cannot be
                  undone.
                </p>
                <div className="decision-actions">
                  <Button disabled={busy} onClick={() => void advance()}>
                    {busy
                      ? "Advancing…"
                      : original
                        ? "Retry original clock advance"
                        : "Confirm global advance"}
                  </Button>
                  {!original && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => setConfirm(false)}
                    >
                      Keep current time
                    </Button>
                  )}
                </div>
              </div>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  review();
                }}
              >
                <label>
                  Advance by seconds
                  <input
                    type="number"
                    min={1}
                    max={31536000}
                    step={1}
                    value={seconds}
                    onChange={(e) => setSeconds(e.target.value)}
                    disabled={busy}
                  />
                </label>
                <Button disabled={busy}>Review clock advance</Button>
              </form>
            )}
            <Button
              variant="secondary"
              disabled={busy || !!original}
              onClick={() => void sweep()}
            >
              {busy ? "Processing…" : "Run pending sweep"}
            </Button>
          </>
        )
      )}
      {result && (
        <div className="sweep-result" role="status">
          <h3>Sweep results</h3>
          <p>
            Scanned {result.scanned} · expired {result.expired} · checked in{" "}
            {result.checked_in} · completed {result.completed} · paid{" "}
            {result.paid} · deferred {result.deferred}
          </p>
          <p>
            {result.has_more
              ? "More changes remain. Run the sweep again to continue."
              : "This batch reports no remaining due changes."}
          </p>
        </div>
      )}
    </section>
  );
}
export function AdminPage() {
  const [action, setAction] = useState("");
  const [target, setTarget] = useState("");
  const [filter, setFilter] = useState({ action: "", target: "" });
  const [data, setData] = useState<{
    items: AuditEvent[];
    next_cursor: string | null;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const generation = useRef<{ active: boolean } | null>(null);
  useEffect(() => {
    const request = { active: true };
    generation.current = request;
    void adminApi
      .events(filter.action, filter.target)
      .then((value) => {
        if (request.active) {
          setBusy(false);
          setData(value);
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
  }, [filter, attempt]);
  async function more() {
    if (!data?.next_cursor || busy) return;
    const request = generation.current;
    setBusy(true);
    try {
      const next = await adminApi.events(
        filter.action,
        filter.target,
        data.next_cursor,
      );
      if (!request?.active) return;
      setData({ ...next, items: [...data.items, ...next.items] });
      setError("");
    } catch (e) {
      if (request?.active) setError(bookingError(e));
    } finally {
      if (request?.active) setBusy(false);
    }
  }
  return (
    <div className="host-layout admin-layout">
      <aside className="host-sidebar">
        <Brand />
        <span className="sidebar-label">Administration</span>
        <a href="#event-log">Event log</a>
        <a href="#demo-clock">Demo clock</a>
        <Link to="/profile">Your profile</Link>
      </aside>
      <main className="host-content">
        <div className="admin-mobile-links">
          <Link to="/profile">Your profile</Link>
          <a href="#demo-clock">Demo clock</a>
        </div>
        <section id="event-log">
          <div className="page-heading">
            <h1>Event log</h1>
            <p>
              Read-only state and money history. Business time and real
              recording time are shown separately.
            </p>
          </div>
          <form
            className="event-filters"
            onSubmit={(e) => {
              e.preventDefault();
              setData(null);
              setFilter({ action: action.trim(), target: target.trim() });
            }}
          >
            <label>
              Action
              <input
                value={action}
                onChange={(e) => setAction(e.target.value)}
                placeholder="reservation.cancelled_by_guest"
              />
            </label>
            <label>
              Target UUID
              <input
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </label>
            <Button>Filter events</Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setData(null);
                setError("");
                setAttempt(attempt + 1);
              }}
            >
              Refresh events
            </Button>
          </form>
          {error && (
            <ErrorState
              message={error}
              retry={() =>
                data?.next_cursor ? void more() : setAttempt(attempt + 1)
              }
            />
          )}{" "}
          {!data && !error ? (
            <p role="status">Loading event history…</p>
          ) : (
            data && (
              <>
                {data.items.length ? (
                  <div className="table-scroll">
                    <table className="financial-table event-table">
                      <caption>Recorded events</caption>
                      <thead>
                        <tr>
                          {[
                            "Business time (UTC)",
                            "Recorded time (UTC)",
                            "Actor",
                            "Action / target",
                            "Before → after",
                          ].map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.items.map((item) => (
                          <tr key={item.id}>
                            <td>{new Date(item.business_at).toISOString()}</td>
                            <td>{new Date(item.recorded_at).toISOString()}</td>
                            <td>
                              <code>
                                {item.actor_id ??
                                  item.system_identity ??
                                  "System"}
                              </code>
                            </td>
                            <td>
                              {item.action}
                              <br />
                              <small>{item.target_type}</small>
                              <code>{item.target_id}</code>
                            </td>
                            <td>
                              <details>
                                <summary>Inspect change</summary>
                                <pre>
                                  {JSON.stringify(
                                    { before: item.before, after: item.after },
                                    null,
                                    2,
                                  )}
                                </pre>
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState title="No matching events">
                    Try a different action or target filter.
                  </EmptyState>
                )}
                {data.next_cursor && (
                  <Button disabled={busy} onClick={() => void more()}>
                    {busy ? "Loading…" : "Load more events"}
                  </Button>
                )}
              </>
            )
          )}
        </section>
        <DemoClock />
      </main>
    </div>
  );
}
