import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../components/ui";
import { monthCells } from "../calendar/monthCells";
import {
  addDays,
  dateString,
  formatDate,
  monthBounds,
  monthLabel,
  shiftMonth,
  validDate,
} from "./dates";
import { StayIcon } from "./StayIcon";

type Range = { check_in: string; check_out: string };
type DateField = keyof Range;
const dayLabel = (value: string) =>
  new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
function monthDate(value: string, offset: number) {
  const month = shiftMonth(value.slice(0, 7), offset);
  const last = new Date(`${monthBounds(month).end}T12:00:00Z`);
  last.setUTCDate(0);
  return `${month}-${String(Math.min(Number(value.slice(8)), last.getUTCDate())).padStart(2, "0")}`;
}
export function DateRangePicker({
  checkIn,
  checkOut,
  minimum,
  disabled = false,
  requireDates = false,
  errors,
  onApply,
}: {
  checkIn: string;
  checkOut: string;
  minimum?: string;
  disabled?: boolean;
  requireDates?: boolean;
  errors: Record<string, string>;
  onApply: (range: Range) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Range>({
    check_in: checkIn,
    check_out: checkOut,
  });
  const [selecting, setSelecting] = useState<DateField>("check_in");
  const [month, setMonth] = useState("");
  const [focusDate, setFocusDate] = useState("");
  const [error, setError] = useState("");
  const [narrow, setNarrow] = useState(
    () => window.matchMedia?.("(max-width: 700px)").matches ?? false,
  );
  const panel = useRef<HTMLDivElement>(null);
  const triggers = useRef<Partial<Record<DateField, HTMLButtonElement | null>>>(
    {},
  );
  const opener = useRef<HTMLButtonElement | null>(null);
  // Business time may arrive after opening. Keep a usable month and roving
  // focus immediately, without replacing the user's draft or trusting device
  // time as an eligibility boundary.
  const activeDate =
    minimum && focusDate && focusDate < minimum ? minimum : focusDate;
  const minimumMonth =
    month && minimum && month < minimum.slice(0, 7)
      ? minimum.slice(0, 7)
      : month;
  const displayedMonth =
    narrow && activeDate.slice(0, 7) > minimumMonth
      ? activeDate.slice(0, 7)
      : minimumMonth;

  useEffect(() => {
    const media = window.matchMedia?.("(max-width: 700px)");
    if (!media) return;
    const changed = () => setNarrow(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  function close(restore = true) {
    setOpen(false);
    if (restore) opener.current?.focus();
  }
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        panel.current?.contains(target) ||
        Object.values(triggers.current).some((node) => node?.contains(target))
      )
        return;
      setOpen(false);
      window.setTimeout(() => opener.current?.focus(), 0);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setOpen(false);
      opener.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  useEffect(() => {
    if (open)
      panel.current
        ?.querySelector<HTMLButtonElement>(`[data-date="${activeDate}"]`)
        ?.focus();
  }, [open, activeDate, displayedMonth]);
  function show(field: DateField, button: HTMLButtonElement) {
    opener.current = button;
    if (open) {
      const selected =
        draft[field] || draft.check_in || minimum || dateString(new Date());
      const target =
        validDate(selected) && (!minimum || selected >= minimum)
          ? selected
          : (minimum ?? dateString(new Date()));
      setSelecting(
        field === "check_out" && validDate(draft.check_in)
          ? "check_out"
          : "check_in",
      );
      setMonth(target.slice(0, 7));
      setFocusDate(target);
      setError("");
      return;
    }
    const preferred =
      field === "check_out" && validDate(checkOut) ? checkOut : checkIn;
    const day =
      validDate(preferred) && (!minimum || preferred >= minimum)
        ? preferred
        : (minimum ?? dateString(new Date()));
    setDraft({ check_in: checkIn, check_out: checkOut });
    setSelecting(
      field === "check_out" && validDate(checkIn) ? "check_out" : "check_in",
    );
    setMonth(day.slice(0, 7));
    setFocusDate(day);
    setError("");
    setOpen(true);
  }
  function select(day: string) {
    setError("");
    if (
      selecting === "check_in" ||
      !validDate(draft.check_in) ||
      day <= draft.check_in
    ) {
      setDraft({ check_in: day, check_out: "" });
      setSelecting("check_out");
    } else {
      setDraft((current) => ({ ...current, check_out: day }));
      setSelecting("check_in");
    }
    setFocusDate(day);
  }
  function reveal(day: string) {
    const clamped = minimum && day < minimum ? minimum : day;
    if (!validDate(clamped)) return;
    const dayMonth = clamped.slice(0, 7);
    if (
      dayMonth < displayedMonth ||
      dayMonth > shiftMonth(displayedMonth, narrow ? 0 : 1)
    )
      setMonth(dayMonth);
    setFocusDate(clamped);
  }
  function keyboard(event: KeyboardEvent<HTMLButtonElement>, day: string) {
    let next: string | undefined;
    if (event.key === "ArrowLeft") next = addDays(day, -1);
    if (event.key === "ArrowRight") next = addDays(day, 1);
    if (event.key === "ArrowUp") next = addDays(day, -7);
    if (event.key === "ArrowDown") next = addDays(day, 7);
    const weekday = (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
    if (event.key === "Home") next = addDays(day, -weekday);
    if (event.key === "End") next = addDays(day, 6 - weekday);
    if (event.key === "PageUp")
      next = monthDate(day, event.shiftKey ? -12 : -1);
    if (event.key === "PageDown")
      next = monthDate(day, event.shiftKey ? 12 : 1);
    if (next) {
      event.preventDefault();
      reveal(next);
    }
  }
  function moveMonth(offset: number) {
    const next = shiftMonth(displayedMonth, offset);
    if (minimum && shiftMonth(next, narrow ? 0 : 1) < minimum.slice(0, 7))
      return;
    setMonth(next);
    const first = `${next}-01`;
    setFocusDate(minimum && first < minimum ? minimum : first);
  }
  function apply() {
    const empty = !draft.check_in && !draft.check_out;
    if (
      (!empty || requireDates) &&
      (!validDate(draft.check_in) || !validDate(draft.check_out))
    ) {
      setError("Choose both a check-in and a check-out date.");
      return;
    }
    if (draft.check_in && minimum && draft.check_in < minimum) {
      setError(
        "Choose a later check-in date for this listing’s local time and booking lead time.",
      );
      return;
    }
    if (draft.check_in && draft.check_out <= draft.check_in) {
      setError("Check-out must be after check-in.");
      return;
    }
    onApply(draft);
    close();
  }
  const nights =
    validDate(draft.check_in) && validDate(draft.check_out)
      ? Math.round(
          (Date.parse(`${draft.check_out}T12:00:00Z`) -
            Date.parse(`${draft.check_in}T12:00:00Z`)) /
            86400000,
        )
      : 0;
  const previousDisabled = minimum && displayedMonth <= minimum.slice(0, 7);
  return (
    <>
      {(["check_in", "check_out"] as const).map((field) => (
        <div key={field} className={`search-field search-${field}`}>
          <label htmlFor={`search-${field}`}>
            {field === "check_in" ? "Check in" : "Check out"}
          </label>
          <button
            ref={(node) => {
              triggers.current[field] = node;
            }}
            type="button"
            id={`search-${field}`}
            className="search-date-trigger"
            aria-label={field === "check_in" ? "Check in" : "Check out"}
            aria-haspopup="dialog"
            aria-expanded={open}
            aria-controls="travel-date-panel"
            aria-invalid={!!errors[field]}
            aria-describedby={`search-${field}-value${errors[field] ? ` search-${field}-error` : ""}`}
            disabled={disabled}
            onClick={(event) => show(field, event.currentTarget)}
          >
            <span id={`search-${field}-value`}>
              {validDate(field === "check_in" ? checkIn : checkOut)
                ? formatDate(field === "check_in" ? checkIn : checkOut)
                : "Add dates"}
            </span>
            <StayIcon name="calendar" />
          </button>
          {errors[field] && (
            <span className="field-error" id={`search-${field}-error`}>
              {errors[field]}
            </span>
          )}
        </div>
      ))}
      {open && (
        <div
          ref={panel}
          className="date-range-panel"
          role="dialog"
          aria-label="Choose travel dates"
          id="travel-date-panel"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              close();
            }
          }}
        >
          <header className="date-range-heading">
            <div>
              <h2>Exact dates</h2>
              <p aria-live="polite">
                {selecting === "check_in"
                  ? "Select check-in date"
                  : "Select check-out date"}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              aria-label="Close dates"
              onClick={() => close()}
            >
              ×
            </Button>
          </header>
          <div className="date-range-navigation">
            <Button
              type="button"
              variant="ghost"
              aria-label="Previous month"
              disabled={!!previousDisabled}
              onClick={() => moveMonth(-1)}
            >
              ‹
            </Button>
            <Button
              type="button"
              variant="ghost"
              aria-label="Next month"
              onClick={() => moveMonth(1)}
            >
              ›
            </Button>
          </div>
          <div className="date-range-months">
            {Array.from({ length: narrow ? 1 : 2 }, (_, index) => {
              const current = shiftMonth(displayedMonth, index),
                cells = monthCells(current);
              return (
                <section
                  className="date-range-month"
                  data-index={index}
                  key={current}
                >
                  <h3>{monthLabel(current)}</h3>
                  <table role="grid" aria-label={monthLabel(current)}>
                    <thead>
                      <tr>
                        {[
                          "Monday",
                          "Tuesday",
                          "Wednesday",
                          "Thursday",
                          "Friday",
                          "Saturday",
                          "Sunday",
                        ].map((weekday) => (
                          <th scope="col" key={weekday} aria-label={weekday}>
                            {weekday.slice(0, 2)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Array.from({ length: cells.length / 7 }, (_, row) => (
                        <tr key={row}>
                          {cells
                            .slice(row * 7, row * 7 + 7)
                            .map((day, column) => {
                              const selected =
                                day === draft.check_in ||
                                day === draft.check_out;
                              const inside =
                                !!day &&
                                !!draft.check_in &&
                                !!draft.check_out &&
                                day > draft.check_in &&
                                day < draft.check_out;
                              return (
                                <td
                                  role="gridcell"
                                  key={day ?? `empty-${column}`}
                                  aria-selected={selected || inside}
                                  data-range={inside || undefined}
                                  data-start={
                                    day === draft.check_in || undefined
                                  }
                                  data-end={
                                    day === draft.check_out || undefined
                                  }
                                >
                                  {day && (
                                    <button
                                      type="button"
                                      data-date={day}
                                      aria-label={dayLabel(day)}
                                      aria-pressed={selected}
                                      tabIndex={day === activeDate ? 0 : -1}
                                      disabled={!!minimum && day < minimum}
                                      onFocus={() => setFocusDate(day)}
                                      onClick={() => select(day)}
                                      onKeyDown={(event) =>
                                        keyboard(event, day)
                                      }
                                    >
                                      {Number(day.slice(8))}
                                    </button>
                                  )}
                                </td>
                              );
                            })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              );
            })}
          </div>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <footer className="date-range-footer">
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setDraft({ check_in: "", check_out: "" });
                setSelecting("check_in");
                setError("");
              }}
            >
              Clear dates
            </Button>
            <p role="status">
              {nights > 0
                ? `${nights} ${nights === 1 ? "night" : "nights"} · ${formatDate(draft.check_in)} – ${formatDate(draft.check_out)}`
                : "Choose your exact dates"}
            </p>
            <Button type="button" onClick={apply}>
              Apply dates
            </Button>
          </footer>
        </div>
      )}
    </>
  );
}
