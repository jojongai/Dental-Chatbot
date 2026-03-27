import type { EmployeeAppointmentRow } from "@/data/employee-appointments";
import AppointmentCard from "./AppointmentCard";

interface DayScheduleProps {
  appointments: EmployeeAppointmentRow[];
}

const DaySchedule = ({ appointments }: DayScheduleProps) => {
  const morning = appointments.filter((a) => {
    const hour = parseInt(a.time, 10);
    return a.time.includes("AM") || hour === 12;
  });
  const afternoon = appointments.filter((a) => {
    return a.time.includes("PM") && !a.time.startsWith("12");
  });

  if (appointments.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
        No appointments scheduled for this day.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-3 px-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Morning</h3>
        <div className="space-y-2">
          {morning.length === 0 ? (
            <p className="text-xs text-muted-foreground">None</p>
          ) : (
            morning.map((apt) => <AppointmentCard key={apt.id} appointment={apt} />)
          )}
        </div>
      </div>
      {afternoon.length > 0 && (
        <div>
          <h3 className="mb-3 px-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Afternoon</h3>
          <div className="space-y-2">
            {afternoon.map((apt) => (
              <AppointmentCard key={apt.id} appointment={apt} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default DaySchedule;
