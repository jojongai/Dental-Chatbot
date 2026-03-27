import type { WeekDayCountRow } from "@/data/employee-appointments";

/** Add calendar days to a YYYY-MM-DD string (local calendar, not UTC shift). */
export function addCalendarDays(iso: string, delta: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + delta);
  const y2 = dt.getFullYear();
  const m2 = String(dt.getMonth() + 1).padStart(2, "0");
  const d2 = String(dt.getDate()).padStart(2, "0");
  return `${y2}-${m2}-${d2}`;
}

export function isTodayIso(iso: string): boolean {
  if (!iso) return false;
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  return iso === today;
}

export function formatScheduleHeading(iso: string): string {
  if (!iso) return "Schedule";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

export function formatWeekRangeLabel(weekDays: WeekDayCountRow[]): string {
  if (weekDays.length < 2) return "";
  const first = weekDays[0].date;
  const last = weekDays[weekDays.length - 1].date;
  const [y1, m1, d1] = first.split("-").map(Number);
  const [y2, m2, d2] = last.split("-").map(Number);
  const a = new Date(y1, m1 - 1, d1);
  const b = new Date(y2, m2 - 1, d2);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (y1 !== y2) {
    opts.year = "numeric";
  }
  return `${a.toLocaleDateString(undefined, opts)} – ${b.toLocaleDateString(undefined, { ...opts, year: "numeric" })}`;
}
