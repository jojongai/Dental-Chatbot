import { cn } from "@/lib/utils";
import type { WeekDayCountRow } from "@/data/employee-appointments";

interface WeekMiniViewProps {
  weekDays: WeekDayCountRow[];
  /** ISO date (YYYY-MM-DD) of the day being viewed — highlights matching pill */
  selectedDate: string;
  onSelectDate: (isoDate: string) => void;
}

const WeekMiniView = ({ weekDays, selectedDate, onSelectDate }: WeekMiniViewProps) => {
  return (
    <div className="flex gap-1.5">
      {weekDays.map((d) => {
        const isSelected = d.date === selectedDate;
        return (
          <button
            key={d.date}
            type="button"
            onClick={() => onSelectDate(d.date)}
            className={cn(
              "flex-1 rounded-lg py-2.5 text-center transition-colors",
              isSelected
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted/50 text-muted-foreground hover:bg-muted",
            )}
          >
            <p className="text-[10px] font-medium uppercase tracking-wide">{d.day}</p>
            <p
              className={cn(
                "mt-0.5 font-display text-lg font-semibold",
                isSelected ? "text-primary-foreground" : "text-foreground",
              )}
            >
              {d.count}
            </p>
            <p className="text-[10px] opacity-70">appts</p>
          </button>
        );
      })}
    </div>
  );
};

export default WeekMiniView;
