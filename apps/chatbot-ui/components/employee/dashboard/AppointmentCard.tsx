import { Clock, User } from "lucide-react";
import type { EmployeeAppointmentRow, UiAppointmentStatus } from "@/data/employee-appointments";
import { cn } from "@/lib/utils";

const statusConfig: Record<UiAppointmentStatus, { label: string; className: string }> = {
  confirmed: { label: "Confirmed", className: "bg-dental-blue-light text-dental-blue" },
  arrived: { label: "Arrived", className: "bg-success-light text-success-foreground" },
  "in-progress": { label: "In Progress", className: "bg-warning-light text-dental-warm-foreground" },
  completed: { label: "Completed", className: "bg-muted text-muted-foreground" },
  cancelled: { label: "Cancelled", className: "bg-muted text-muted-foreground line-through" },
};

/** Left border accent by appointment type code from API */
const codeColorMap: Record<string, string> = {
  cleaning: "border-l-dental-teal",
  general_checkup: "border-l-primary",
  emergency: "border-l-emergency",
  new_patient_exam: "border-l-dental-blue",
};

interface AppointmentCardProps {
  appointment: EmployeeAppointmentRow;
}

const AppointmentCard = ({ appointment }: AppointmentCardProps) => {
  const status = statusConfig[appointment.uiStatus] ?? statusConfig.confirmed;
  const borderColor =
    codeColorMap[appointment.appointmentTypeCode] ?? "border-l-primary";
  const isCompleted = appointment.uiStatus === "completed";

  return (
    <div
      className={cn(
        "rounded-lg border border-l-[3px] border-border bg-card p-3.5 shadow-sm transition-all hover:shadow-md",
        borderColor,
        isCompleted && "opacity-60",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={cn("text-sm font-medium text-card-foreground", isCompleted && "line-through")}>
            {appointment.patientName}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{appointment.type}</p>
        </div>
        <span
          className={cn(
            "whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium",
            status.className,
          )}
        >
          {status.label}
        </span>
      </div>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {appointment.time} · {appointment.duration}min
        </span>
        <span className="flex items-center gap-1">
          <User className="h-3 w-3" />
          {appointment.provider}
        </span>
      </div>
    </div>
  );
};

export default AppointmentCard;
