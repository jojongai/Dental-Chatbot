import { CalendarCheck, Clock, Users, TrendingUp } from "lucide-react";
import type { EmployeeAppointmentRow, WeekDayCountRow } from "@/data/employee-appointments";
import { isTodayIso } from "@/lib/calendar";
import { cn } from "@/lib/utils";
import WeekMiniView from "./WeekMiniView";

interface SidePanelProps {
  appointments: EmployeeAppointmentRow[];
  weekDays: WeekDayCountRow[];
  selectedDate: string;
  providerCount: number;
  onSelectDate: (isoDate: string) => void;
}

const SidePanel = ({
  appointments,
  weekDays,
  selectedDate,
  providerCount,
  onSelectDate,
}: SidePanelProps) => {
  const total = appointments.length;
  const completed = appointments.filter((a) => a.uiStatus === "completed").length;
  const upcoming = appointments.filter(
    (a) => a.uiStatus === "confirmed" || a.uiStatus === "arrived",
  );
  const nextUp = upcoming[0];
  const today = isTodayIso(selectedDate);

  const stats = [
    { label: today ? "Total today" : "Total (day)", value: total, icon: CalendarCheck, color: "text-primary" },
    { label: "Completed", value: completed, icon: TrendingUp, color: "text-success" },
    { label: "Remaining", value: upcoming.length, icon: Clock, color: "text-dental-blue" },
    { label: "Providers", value: providerCount, icon: Users, color: "text-dental-teal" },
  ];

  return (
    <aside className="space-y-5">
      <div className="grid grid-cols-2 gap-2.5">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-border bg-card p-3.5 shadow-sm">
            <s.icon className={cn("mb-1.5 h-4 w-4", s.color)} />
            <p className="font-display text-2xl font-bold text-foreground">{s.value}</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
        <h3 className="mb-3 font-display text-sm font-semibold text-foreground">This week</h3>
        <WeekMiniView weekDays={weekDays} selectedDate={selectedDate} onSelectDate={onSelectDate} />
      </div>

      {nextUp && (
        <div className="rounded-xl border border-dental-teal/20 bg-dental-teal-light p-4">
          <h3 className="mb-2 font-display text-sm font-semibold text-foreground">Up next</h3>
          <p className="text-sm font-medium text-foreground">{nextUp.patientName}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {nextUp.type} · {nextUp.time} · {nextUp.provider}
          </p>
          <div className="mt-2.5 flex gap-2">
            <button
              type="button"
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              Check In
            </button>
            <button
              type="button"
              className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              Details
            </button>
          </div>
        </div>
      )}
    </aside>
  );
};

export default SidePanel;
