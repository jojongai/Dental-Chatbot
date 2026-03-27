import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import type { WeekDayCountRow } from "@/data/employee-appointments";
import { addCalendarDays, formatWeekRangeLabel } from "@/lib/calendar";

interface ScheduleDateNavProps {
  selectedDate: string;
  weekDays: WeekDayCountRow[];
  onSelectDate: (isoDate: string) => void;
  disabled?: boolean;
}

/**
 * Previous/next week jumps keep the same weekday (e.g. Wed → Wed).
 */
const ScheduleDateNav = ({
  selectedDate,
  weekDays,
  onSelectDate,
  disabled,
}: ScheduleDateNavProps) => {
  const range = formatWeekRangeLabel(weekDays);

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={disabled || !selectedDate}
        onClick={() => selectedDate && onSelectDate(addCalendarDays(selectedDate, -7))}
        className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground shadow-sm transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Week
      </button>
      {range && (
        <span className="text-xs text-muted-foreground tabular-nums" aria-live="polite">
          {range}
        </span>
      )}
      <button
        type="button"
        disabled={disabled || !selectedDate}
        onClick={() => selectedDate && onSelectDate(addCalendarDays(selectedDate, 7))}
        className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground shadow-sm transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      >
        Week
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
      <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <CalendarDays className="h-3.5 w-3.5" />
        <span className="sr-only">Go to date</span>
        <input
          type="date"
          disabled={disabled}
          value={selectedDate || ""}
          onChange={(e) => {
            const v = e.target.value;
            if (v) onSelectDate(v);
          }}
          className="rounded-md border border-border bg-background px-2 py-1 text-foreground disabled:opacity-40"
        />
      </label>
    </div>
  );
};

export default ScheduleDateNav;
