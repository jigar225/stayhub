import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { listingsApi, type Listing } from "../listings/api";
import {
  addDays,
  dateString,
  formatDate,
  monthBounds,
  monthLabel,
  shiftMonth,
  validDate,
} from "../discovery/dates";
import { calendarApi, type CalendarOccupancy, type CalendarData } from "./api";
import { MonthGrid } from "./MonthGrid";
export function HostCalendar() {
  const [params, setParams] = useSearchParams();
  const [listings, setListings] = useState<Listing[] | null>(null);
  const [listError, setListError] = useState("");
  const [listAttempt, setListAttempt] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const requestedId = params.get("listing");
  const selectedId = requestedId ?? listings?.[0]?.id ?? "";
  const rawMonth = params.get("month") ?? dateString(new Date()).slice(0, 7);
  const month =
    /^\d{4}-\d{2}$/.test(rawMonth) && validDate(`${rawMonth}-01`)
      ? rawMonth
      : dateString(new Date()).slice(0, 7);
  const bounds = monthBounds(month);
  const key = `${selectedId}-${month}`;
  const [data, setData] = useState<{ key: string; value: CalendarData } | null>(
    null,
  );
  const [error, setError] = useState<{ key: string; message: string } | null>(
    null,
  );
  const [attempt, setAttempt] = useState(0);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [selection, setSelection] = useState<CalendarOccupancy | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [notice, setNotice] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    void listingsApi
      .list()
      .then((result) => {
        if (active) {
          setListings(result.items);
          setCursor(result.next_cursor);
        }
      })
      .catch((e) => {
        if (active)
          setListError(
            e instanceof Error ? e.message : "Could not load your listings.",
          );
      });
    return () => {
      active = false;
    };
  }, [listAttempt]);
  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    const controller = new AbortController();
    void calendarApi
      .read(selectedId, bounds.start, bounds.end, controller.signal)
      .then((result) => {
        if (active) {
          setData({ key, value: result });
          setError(null);
        }
      })
      .catch((e) => {
        if (active)
          setError({
            key,
            message:
              e instanceof Error ? e.message : "Could not load calendar.",
          });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedId, bounds.start, bounds.end, key, attempt]);
  async function more() {
    if (!cursor) return;
    setMoreBusy(true);
    try {
      const result = await listingsApi.list(cursor);
      setListings((current) => [...(current ?? []), ...result.items]);
      setCursor(result.next_cursor);
    } catch (e) {
      setListError(
        e instanceof Error ? e.message : "Could not load more listings.",
      );
    } finally {
      setMoreBusy(false);
    }
  }
  function updateParams(id: string, nextMonth: string) {
    const next = new URLSearchParams(params);
    next.set("listing", id);
    next.set("month", nextMonth);
    setParams(next);
    setSelection(null);
    setStart("");
    setEnd("");
    setSelecting(false);
    setMutationError("");
    setNotice("");
    setFieldErrors({});
  }
  function choose(date: string, block?: CalendarOccupancy) {
    setMutationError("");
    setNotice("");
    setFieldErrors({});
    if (block) {
      setSelection(block);
      setStart(block.check_in);
      setEnd(block.check_out);
      setSelecting(false);
    } else {
      setSelection(null);
      if (selecting && date >= start) {
        setEnd(addDays(date, 1));
        setSelecting(false);
      } else {
        setStart(date);
        setEnd(addDays(date, 1));
        setSelecting(true);
      }
    }
  }
  function describe(e: unknown) {
    if (e instanceof ApiError && e.details.field_errors)
      setFieldErrors(
        Object.fromEntries(
          Object.entries(e.details.field_errors).map(([field, message]) => [
            field,
            Array.isArray(message) ? message.join(" ") : message,
          ]),
        ),
      );
    setMutationError(
      e instanceof Error ? e.message : "Could not update availability.",
    );
  }
  async function block() {
    const errors: Record<string, string> = {};
    if (!validDate(start)) errors.check_in = "Choose a valid start date.";
    if (!validDate(end) || end <= start)
      errors.check_out = "End date must be after the start date.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      document
        .getElementById(
          Object.keys(errors)[0] === "check_in" ? "block-start" : "block-end",
        )
        ?.focus();
      return;
    }
    setBusy(true);
    setMutationError("");
    setNotice("");
    try {
      await calendarApi.block(selectedId, start, end);
      setNotice(
        `Dates blocked: ${formatDate(start)} – ${formatDate(end)} (end excluded).`,
      );
      setSelection(null);
      setAttempt(attempt + 1);
    } catch (e) {
      describe(e);
    } finally {
      setBusy(false);
    }
  }
  async function unblock(blockId: string) {
    setBusy(true);
    setMutationError("");
    setNotice("");
    try {
      await calendarApi.unblock(selectedId, blockId);
      setNotice("Dates are available again.");
      setSelection(null);
      setStart("");
      setEnd("");
      setSelecting(false);
      setAttempt(attempt + 1);
    } catch (e) {
      describe(e);
    } finally {
      setBusy(false);
    }
  }
  if (listError && !listings)
    return (
      <main className="host-content">
        <ErrorState
          message={listError}
          retry={() => {
            setListError("");
            setListAttempt(listAttempt + 1);
          }}
        />
      </main>
    );
  if (!listings)
    return (
      <main className="host-content" role="status">
        Loading your listings…
      </main>
    );
  if (!listings.length)
    return (
      <main className="host-content">
        <h1>Calendar</h1>
        <EmptyState
          title="Your calendar starts with a place"
          action={
            <Link className="button primary" to="/host/listings">
              Manage listings
            </Link>
          }
        >
          Create your first listing, then manage its available nights here.
        </EmptyState>
      </main>
    );
  const current = data?.key === key ? data.value : null;
  const currentError = error?.key === key ? error.message : null;
  const selectedListing = listings.find((listing) => listing.id === selectedId);
  return (
    <main className="host-content host-calendar">
      <div className="page-heading">
        <h1>Calendar</h1>
        <p>Make room for your plans. Block nights you don’t want to host.</p>
      </div>
      <div className="calendar-toolbar">
        <label>
          Listing
          <select
            aria-label="Calendar listing"
            value={selectedId}
            disabled={busy}
            onChange={(event) => updateParams(event.target.value, month)}
          >
            {requestedId && !selectedListing && (
              <option value={requestedId}>Selected listing</option>
            )}
            {listings.map((listing) => (
              <option value={listing.id} key={listing.id}>
                {listing.title ?? "Untitled listing"} · {listing.status}
              </option>
            ))}
          </select>
        </label>
        {cursor && (
          <Button
            variant="secondary"
            disabled={moreBusy}
            onClick={() => void more()}
          >
            {moreBusy ? "Loading…" : "Load more listings"}
          </Button>
        )}
        <div className="month-navigation">
          <Button
            variant="secondary"
            aria-label="Previous month"
            disabled={busy}
            onClick={() => updateParams(selectedId, shiftMonth(month, -1))}
          >
            ‹
          </Button>
          <h2>{monthLabel(month)}</h2>
          <Button
            variant="secondary"
            aria-label="Next month"
            disabled={busy}
            onClick={() => updateParams(selectedId, shiftMonth(month, 1))}
          >
            ›
          </Button>
        </div>
      </div>
      {listError && (
        <ErrorState message={listError} retry={() => void more()} />
      )}
      <div className="calendar-legend">
        <span>
          <i className="available-swatch" />
          Available
        </span>
        <span>
          <i className="blocked-swatch" />
          Blocked
        </span>
        <span>
          <i className="pending-swatch" />
          Pending
        </span>
        <span>
          <i className="confirmed-swatch" />
          Confirmed
        </span>
        <span>
          <i className="checked-in-swatch" />
          Checked in
        </span>
        <span>
          <i className="completed-swatch" />
          Completed
        </span>
        <span className="muted">
          {current?.timezone ??
            selectedListing?.timezone ??
            "Listing local dates"}
        </span>
      </div>
      {rawMonth !== month && (
        <p className="field-error">
          The requested month was invalid. Showing the current month.
        </p>
      )}
      {currentError ? (
        <ErrorState
          message={currentError}
          retry={() => setAttempt(attempt + 1)}
        />
      ) : !current ? (
        <p role="status">Loading availability…</p>
      ) : (
        <div className="calendar-columns">
          <div className="calendar-board">
            <MonthGrid
              month={month}
              blocks={current.items}
              onSelect={choose}
              selectedStart={start}
              selectedEnd={end}
              disabled={busy}
            />
            <p className="calendar-footnote">
              Select a start night, then a last night. The form’s end date is
              excluded. Available nights have no active block or reservation.
            </p>
          </div>
          <aside className="calendar-actions card">
            <h2>
              {selection?.kind === "reservation"
                ? "Reservation occupancy"
                : selection
                  ? "Blocked dates"
                  : "Manage availability"}
            </h2>
            <p className="muted">
              Dates use the listing’s local timezone. Check-out/end is excluded.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void block();
              }}
            >
              <label htmlFor="block-start">
                Block from
                <input
                  id="block-start"
                  type="date"
                  value={start}
                  disabled={busy || !!selection}
                  onChange={(e) => {
                    setStart(e.target.value);
                    setSelecting(false);
                  }}
                  aria-invalid={!!fieldErrors.check_in}
                  aria-describedby="block-start-error"
                />
              </label>
              <span className="field-error" id="block-start-error">
                {fieldErrors.check_in}
              </span>
              <label htmlFor="block-end">
                Until (exclusive)
                <input
                  id="block-end"
                  type="date"
                  value={end}
                  disabled={busy || !!selection}
                  onChange={(e) => {
                    setEnd(e.target.value);
                    setSelecting(false);
                  }}
                  aria-invalid={!!fieldErrors.check_out}
                  aria-describedby="block-end-error"
                />
              </label>
              <span className="field-error" id="block-end-error">
                {fieldErrors.check_out}
              </span>
              {selection?.kind === "reservation" ? (
                <p>
                  <strong>
                    {selection.state === "pending"
                      ? "Pending"
                      : selection.state === "checked_in"
                        ? "Checked in"
                        : selection.state === "completed"
                          ? "Completed"
                          : "Confirmed"}{" "}
                    · {selection.code}
                  </strong>
                  <br />
                  <Link to={`/trips/${selection.reservation_id}`}>
                    View reservation
                  </Link>
                  <br />
                  Reservation dates cannot be unblocked.
                </p>
              ) : selection ? (
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => void unblock(selection.id)}
                >
                  {busy ? "Updating…" : "Unblock selected dates"}
                </Button>
              ) : (
                <Button disabled={busy}>
                  {busy ? "Blocking…" : "Block dates"}
                </Button>
              )}
              {selection && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    setSelection(null);
                    setStart("");
                    setEnd("");
                  }}
                >
                  Clear selection
                </Button>
              )}
            </form>
            {mutationError && <ErrorState message={mutationError} />}{" "}
            {notice && (
              <p className="calendar-notice" role="status">
                {notice}
              </p>
            )}
            <section className="block-list">
              <h3>Blocks this month</h3>
              {current.items.some((item) => item.kind === "block") ? (
                current.items
                  .filter((item) => item.kind === "block")
                  .map((item) => (
                    <div key={item.id}>
                      <p>
                        {formatDate(item.check_in)} –{" "}
                        {formatDate(item.check_out)}
                      </p>
                      <span className="field-help">End excluded</span>
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => void unblock(item.id)}
                        aria-label={`Unblock ${item.check_in} to ${item.check_out}`}
                      >
                        Unblock
                      </Button>
                    </div>
                  ))
              ) : (
                <p className="muted">No blocked nights this month.</p>
              )}
            </section>
          </aside>
        </div>
      )}
    </main>
  );
}
