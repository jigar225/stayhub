import { addDays, monthBounds } from "../discovery/dates";
export function monthCells(month: string) {
  const { start, end } = monthBounds(month);
  const offset = (new Date(`${start}T12:00:00Z`).getUTCDay() + 6) % 7;
  const cells: (string | null)[] = Array.from({ length: offset }, () => null);
  for (let day = start; day < end; day = addDays(day, 1)) cells.push(day);
  while (cells.length % 7) cells.push(null);
  return cells;
}
