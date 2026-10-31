import { formatDate, monthLabel } from "../discovery/dates";
import { monthCells } from "./monthCells";
import type { CalendarOccupancy } from "./api";
export function MonthGrid({
  month,
  blocks,
  onSelect,
  selectedStart,
  selectedEnd,
  disabled = false,
  minDate,
  maxDate,
  today,
}: {
  month: string;
  blocks: CalendarOccupancy[];
  onSelect: (date: string, block?: CalendarOccupancy) => void;
  selectedStart: string;
  selectedEnd: string;
  disabled?: boolean;
  minDate?: string;
  maxDate?: string;
  today?: string;
}) {
  const cells = monthCells(month);
  return (
    <table
      className="month-grid"
      aria-label={`${monthLabel(month)} availability`}
    >
      <thead>
        <tr>
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
            <th key={day} scope="col">
              <abbr
                title={
                  day === "Mon"
                    ? "Monday"
                    : day === "Tue"
                      ? "Tuesday"
                      : day === "Wed"
                        ? "Wednesday"
                        : day === "Thu"
                          ? "Thursday"
                          : day === "Fri"
                            ? "Friday"
                            : day === "Sat"
                              ? "Saturday"
                              : "Sunday"
                }
              >
                {day}
              </abbr>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: cells.length / 7 }, (_, week) => (
          <tr key={week}>
            {cells.slice(week * 7, week * 7 + 7).map((date, index) => {
              const block = date
                ? blocks.find(
                    (item) => item.check_in <= date && date < item.check_out,
                  )
                : undefined;
              const outside =
                !!date &&
                ((!!minDate && date < minDate) ||
                  (!!maxDate && date >= maxDate));
              const past = !!date && !!today && date < today;
              const label = outside
                ? "Outside available range"
                : block?.kind === "reservation"
                  ? block.state === "pending"
                    ? "Pending"
                    : block.state === "checked_in"
                      ? "Checked in"
                      : block.state === "completed"
                        ? "Completed"
                        : "Confirmed"
                  : block
                    ? "Blocked"
                    : past
                      ? "Past date"
                      : "Available";
              return (
                <td key={date ?? `empty-${index}`}>
                  {date && (
                    <button
                      type="button"
                      disabled={disabled || outside || (past && !block)}
                      className={`${block?.kind === "reservation" ? block.state : block ? "blocked" : "available"} ${selectedStart && selectedStart <= date && date < selectedEnd ? "date-selected" : ""}`}
                      aria-label={`${formatDate(date)}, ${label}`}
                      aria-pressed={
                        !!(
                          selectedStart &&
                          selectedStart <= date &&
                          date < selectedEnd
                        )
                      }
                      onClick={() => onSelect(date, block)}
                    >
                      <span>{Number(date.slice(-2))}</span>
                      <small>{label}</small>
                    </button>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
