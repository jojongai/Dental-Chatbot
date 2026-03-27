/**
 * Shared types for the employee schedule UI (data comes from GET /v1/employee/schedule).
 */

export type UiAppointmentStatus = "confirmed" | "arrived" | "in-progress" | "completed" | "cancelled";

export interface EmployeeAppointmentRow {
  id: string;
  patientName: string;
  /** Appointment type label from API */
  type: string;
  appointmentTypeCode: string;
  /** e.g. "8:00 AM" */
  time: string;
  duration: number;
  provider: string;
  uiStatus: UiAppointmentStatus;
  isEmergency?: boolean;
}

export interface EmployeeEmergencyRow {
  id: string;
  patientName: string;
  description: string;
  time: string;
  severity: "urgent" | "critical";
}

export interface WeekDayCountRow {
  day: string;
  count: number;
  date: string;
}
