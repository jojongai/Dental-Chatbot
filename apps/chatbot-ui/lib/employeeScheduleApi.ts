/**
 * GET /v1/employee/schedule — day view + week counts (FastAPI).
 */

const apiBase = () =>
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "http://127.0.0.1:8000";

export interface EmployeeScheduleApiAppointment {
  id: string;
  patient_name: string;
  appointment_type_display: string;
  appointment_type_code: string;
  time_start: string;
  duration_minutes: number;
  provider_display_name: string | null;
  status: string;
  ui_status: string;
  is_emergency: boolean;
}

export interface EmployeeScheduleApiEmergency {
  id: string;
  patient_name: string;
  description: string;
  time: string;
  severity: string;
}

export interface EmployeeScheduleApiWeekDay {
  day: string;
  count: number;
  date: string;
}

export interface EmployeeScheduleApiResponse {
  date: string;
  timezone: string;
  appointments: EmployeeScheduleApiAppointment[];
  emergency_alerts: EmployeeScheduleApiEmergency[];
  week_day_counts: EmployeeScheduleApiWeekDay[];
  provider_count: number;
}

export async function fetchEmployeeSchedule(dateIso?: string): Promise<EmployeeScheduleApiResponse> {
  const u = new URL(`${apiBase().replace(/\/$/, "")}/v1/employee/schedule`);
  if (dateIso) u.searchParams.set("date", dateIso);
  const res = await fetch(u.toString(), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Schedule request failed (${res.status})`);
  }
  return res.json() as Promise<EmployeeScheduleApiResponse>;
}
