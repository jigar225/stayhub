import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { formatEUR } from "../listings/form";
import { bookingApi, bookingError, type EarningsData } from "./api";
export function Earnings() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const [data, setData] = useState<{
    status: string;
    value: EarningsData;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const generation = useRef<{ active: boolean } | null>(null);
  useEffect(() => {
    const request = { active: true };
    generation.current = request;
    void bookingApi
      .earnings(status)
      .then((value) => {
        if (request.active) {
          setBusy(false);
          setData({ status, value });
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
  }, [status, attempt]);
  const current = data?.status === status ? data.value : null;
  async function more() {
    if (!current?.next_cursor || busy) return;
    const request = generation.current;
    setBusy(true);
    try {
      const next = await bookingApi.earnings(status, current.next_cursor);
      if (!request?.active) return;
      setData({
        status,
        value: { ...next, items: [...current.items, ...next.items] },
      });
      setError("");
    } catch (e) {
      if (request?.active) setError(bookingError(e));
    } finally {
      if (request?.active) setBusy(false);
    }
  }
  return (
    <main className="host-content earnings-page">
      <div className="page-heading">
        <h1>Earnings</h1>
        <p>
          Simulated host payments. Amounts below come from your booked stays and
          refunds.
        </p>
      </div>
      {error && (
        <ErrorState
          message={error}
          retry={() =>
            current?.next_cursor ? void more() : setAttempt(attempt + 1)
          }
        />
      )}
      {!current && !error ? (
        <p role="status">Loading earnings…</p>
      ) : (
        current && (
          <>
            <div className="earnings-totals">
              {(
                [
                  ["Paid", current.totals.paid_minor],
                  ["Upcoming", current.totals.upcoming_minor],
                  ["Held", current.totals.held_minor],
                ] as const
              ).map(([label, amount]) => (
                <section className="card" key={label}>
                  <h2>{label}</h2>
                  <strong>{formatEUR(amount)}</strong>
                  <p>
                    {label === "Paid"
                      ? "Simulated payments released"
                      : label === "Upcoming"
                        ? "Scheduled host earnings"
                        : "Requests awaiting host acceptance"}
                  </p>
                </section>
              ))}
            </div>
            <p className="field-help">
              Totals include all your stays, regardless of the visible page or
              status filter. Zero and cancelled earnings are excluded.
            </p>
            <label className="earnings-filter">
              Payout status
              <select
                value={status}
                onChange={(e) => {
                  setError("");
                  setParams(e.target.value ? { status: e.target.value } : {});
                }}
              >
                <option value="">All statuses</option>
                {["held", "scheduled", "paid", "cancelled"].map((s) => (
                  <option value={s} key={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            {current.items.length ? (
              <div className="table-scroll">
                <table className="financial-table">
                  <caption>Host earnings by reservation</caption>
                  <thead>
                    <tr>
                      {[
                        "Reservation / stay",
                        "Gross",
                        "Host fee",
                        "Host net",
                        "Due (UTC)",
                        "Paid (UTC)",
                        "Status",
                      ].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {current.items.map((p) => (
                      <tr key={p.id}>
                        <td>
                          <Link to={`/trips/${p.reservation_id}`}>
                            {p.listing_title}
                          </Link>
                          <code>{p.code}</code>
                          {p.retained_cancellation && (
                            <span className="retained-label">
                              Retained cancellation earnings
                            </span>
                          )}
                        </td>
                        <td>{formatEUR(p.gross_minor)}</td>
                        <td>{formatEUR(p.host_fee_minor)}</td>
                        <td>
                          <strong>{formatEUR(p.net_minor)}</strong>
                        </td>
                        <td>
                          {new Date(p.due_at).toLocaleString("en-GB", {
                            timeZone: "UTC",
                          })}
                        </td>
                        <td>
                          {p.paid_at
                            ? new Date(p.paid_at).toLocaleString("en-GB", {
                                timeZone: "UTC",
                              })
                            : "—"}
                        </td>
                        <td>
                          <span className={`reservation-status ${p.status}`}>
                            {p.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No earnings in this category">
                Your real reservations will appear here with their
                server-calculated host earnings.
              </EmptyState>
            )}
            {current.next_cursor && (
              <Button disabled={busy} onClick={() => void more()}>
                {busy ? "Loading…" : "Load more earnings"}
              </Button>
            )}
          </>
        )
      )}
    </main>
  );
}
