import { useEffect, useRef, useState } from "react";
import { useBusinessTime } from "../api/businessTime";
import { Button, ErrorState } from "../components/ui";
import { monthCells } from "../calendar/monthCells";
import { discoveryApi, type PublicDetail, type UnavailableRange } from "./api";
import {
  addDays,
  earliestCheckIn,
  formatDate,
  monthBounds,
  monthLabel,
  shiftMonth,
  validDate,
} from "./dates";

type Dates = { check_in: string; check_out: string };
function localDay(now: Date, timezone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: timezone,
  }).formatToParts(now);
  return ["year", "month", "day"]
    .map((key) => parts.find((part) => part.type === key)?.value)
    .join("-");
}
export function StayAvailability({
  listing,
  checkIn,
  checkOut,
  onApply,
}: {
  listing: PublicDetail;
  checkIn: string;
  checkOut: string;
  onApply: (range: Dates) => void;
}) {
  const clock = useBusinessTime();
  const minimum = clock.now ? earliestCheckIn(listing, clock.now) : "";
  const today = clock.now ? localDay(clock.now, listing.timezone) : "";
  const maximum = today ? addDays(today, 730) : "";
  const [month, setMonth] = useState("");
  const [selection, setSelection] = useState<Dates | null>(null);
  const draft = selection ?? { check_in: checkIn, check_out: checkOut };
  const [data, setData] = useState<{
    key: string;
    unavailable: UnavailableRange[];
  } | null>(null);
  const [loadedRanges, setLoadedRanges] = useState<
    Record<string, UnavailableRange[]>
  >({});
  const [failure, setFailure] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selectionError, setSelectionError] = useState("");
  const [focusDay, setFocusDay] = useState("");
  const grid = useRef<HTMLTableElement>(null);
  const initialMonth =
    validDate(checkIn) && checkIn >= minimum && (!maximum || checkIn < maximum)
      ? checkIn.slice(0, 7)
      : minimum.slice(0, 7);
  const visibleMonth = month || initialMonth;
  const bounds = visibleMonth ? monthBounds(visibleMonth) : null;
  const start =
    bounds && today
      ? bounds.start < addDays(today, -31)
        ? addDays(today, -31)
        : bounds.start
      : "";
  const end =
    bounds && maximum ? (bounds.end > maximum ? maximum : bounds.end) : "";
  const key = `${listing.id}:${start}:${end}:${attempt}`;
  useEffect(() => {
    if (!start || !end || start >= end) return;
    const controller = new AbortController();
    void discoveryApi
      .availability(listing.id, start, end, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setData({ key, unavailable: result.unavailable });
          setLoadedRanges((prior) => ({
            ...prior,
            [start]: result.unavailable,
          }));
          setFailure(null);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setFailure({
            key,
            message:
              "Availability could not be loaded. Retry, or check your dates in the booking panel.",
          });
      });
    return () => controller.abort();
  }, [listing.id, start, end, key]);
  const current = data?.key === key ? data : null;
  const error = failure?.key === key ? failure.message : "";
  const ranges = [
    ...Object.values(loadedRanges).flat(),
    ...(current?.unavailable ?? []),
  ];
  const occupied = (day: string) =>
    ranges.some((range) => range.check_in <= day && day < range.check_out);
  function choose(day: string) {
    setSelectionError("");
    if (!draft.check_in || draft.check_out || day <= draft.check_in) {
      if (!occupied(day)) setSelection({ check_in: day, check_out: "" });
      return;
    }
    if (
      ranges.some(
        (range) => range.check_in < day && range.check_out > draft.check_in,
      )
    ) {
      setSelectionError(
        "These nights include unavailable dates. Choose another range.",
      );
      return;
    }
    setSelection({ check_in: draft.check_in, check_out: day });
  }
  const canApply =
    !!current &&
    validDate(draft.check_in) &&
    validDate(draft.check_out) &&
    draft.check_out > draft.check_in &&
    (!minimum || draft.check_in >= minimum) &&
    !ranges.some(
      (range) =>
        range.check_in < draft.check_out && range.check_out > draft.check_in,
    );
  function shift(offset: number) {
    setMonth(shiftMonth(visibleMonth, offset));
    setFocusDay("");
  }
  useEffect(() => {
    if (focusDay)
      grid.current
        ?.querySelector<HTMLButtonElement>(`[data-date="${focusDay}"]`)
        ?.focus();
  }, [focusDay, current]);
  return (
    <section
      className="preview-section stay-availability"
      aria-labelledby="availability-title"
    >
      <h2 id="availability-title">Availability</h2>
      <p>
        Choose nights for your stay. Availability can change until your
        reservation is confirmed.
      </p>
      <p className="field-help">
        Dates and check-in times use {listing.timezone}. Unavailable dates refer
        to nights; check-out may fall on an unavailable night.
      </p>
      {clock.error && (
        <p role="status">
          {clock.error}{" "}
          <Button
            variant="secondary"
            type="button"
            onClick={() => void clock.refresh()}
          >
            Retry availability time
          </Button>
        </p>
      )}
      {!visibleMonth ? (
        <p role="status">Loading availability time…</p>
      ) : (
        <>
          <div className="availability-toolbar">
            <Button
              type="button"
              variant="secondary"
              aria-label="Previous availability month"
              disabled={visibleMonth <= minimum.slice(0, 7)}
              onClick={() => shift(-1)}
            >
              ←
            </Button>
            <h3 aria-live="polite">{monthLabel(visibleMonth)}</h3>
            <Button
              type="button"
              variant="secondary"
              aria-label="Next availability month"
              disabled={
                !!maximum && `${shiftMonth(visibleMonth, 1)}-01` >= maximum
              }
              onClick={() => shift(1)}
            >
              →
            </Button>
          </div>
          {error ? (
            <ErrorState
              message={error}
              retry={() => setAttempt((value) => value + 1)}
            />
          ) : (
            <>
              {!current && <p role="status">Loading availability…</p>}
              <table
                ref={grid}
                className="availability-grid"
                aria-label={`${monthLabel(visibleMonth)} stay availability`}
                aria-busy={!current}
              >
                <thead>
                  <tr>
                    {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(
                      (day) => (
                        <th key={day} scope="col">
                          {day}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {Array.from(
                    { length: monthCells(visibleMonth).length / 7 },
                    (_, row) => (
                      <tr key={row}>
                        {monthCells(visibleMonth)
                          .slice(row * 7, row * 7 + 7)
                          .map((day, column) => (
                            <td key={day ?? `empty-${column}`}>
                              {day && (
                                <button
                                  type="button"
                                  data-date={day}
                                  data-unavailable={occupied(day) || undefined}
                                  data-selected={
                                    day === draft.check_in ||
                                    day === draft.check_out ||
                                    undefined
                                  }
                                  data-range={
                                    (!!draft.check_in &&
                                      !!draft.check_out &&
                                      day > draft.check_in &&
                                      day < draft.check_out) ||
                                    undefined
                                  }
                                  aria-label={`${formatDate(day)}, ${!current ? "Loading" : occupied(day) ? "Unavailable night" : "Available night"}`}
                                  aria-pressed={
                                    day === draft.check_in ||
                                    day === draft.check_out
                                  }
                                  disabled={
                                    !current ||
                                    day < minimum ||
                                    day >= maximum ||
                                    (occupied(day) &&
                                      (!draft.check_in ||
                                        !!draft.check_out ||
                                        day <= draft.check_in))
                                  }
                                  onFocus={() => setFocusDay(day)}
                                  onClick={() => choose(day)}
                                  onKeyDown={(event) => {
                                    const offset = {
                                      ArrowLeft: -1,
                                      ArrowRight: 1,
                                      ArrowUp: -7,
                                      ArrowDown: 7,
                                    }[event.key];
                                    if (offset === undefined) return;
                                    event.preventDefault();
                                    const next = addDays(day, offset);
                                    if (next < minimum || next >= maximum)
                                      return;
                                    if (next.slice(0, 7) !== visibleMonth)
                                      setMonth(next.slice(0, 7));
                                    setFocusDay(next);
                                  }}
                                >
                                  {Number(day.slice(8))}
                                </button>
                              )}
                            </td>
                          ))}
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
              <div className="availability-legend">
                <span>Available nights</span>
                <span className="unavailable">Unavailable nights</span>
                <span className="selected">Your selected dates</span>
              </div>
              <p role="status">
                {draft.check_in
                  ? `${formatDate(draft.check_in)}${draft.check_out ? ` – ${formatDate(draft.check_out)}` : " · Choose check-out"}`
                  : "Choose check-in, then check-out"}
              </p>
              {selectionError && (
                <p role="alert" className="field-error">
                  {selectionError}
                </p>
              )}
              <div className="availability-actions">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setSelection({ check_in: "", check_out: "" });
                    setSelectionError("");
                  }}
                >
                  Clear selection
                </Button>
                <Button
                  type="button"
                  disabled={!canApply}
                  onClick={() => {
                    onApply(draft);
                    setSelection(null);
                  }}
                >
                  Check these dates
                </Button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
