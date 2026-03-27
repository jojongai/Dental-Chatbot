"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import DashboardHeader from "@/components/employee/dashboard/DashboardHeader";
import EmergencyBanner from "@/components/employee/dashboard/EmergencyBanner";
import DaySchedule from "@/components/employee/dashboard/DaySchedule";
import ScheduleDateNav from "@/components/employee/dashboard/ScheduleDateNav";
import SidePanel from "@/components/employee/dashboard/SidePanel";
import WeekMiniView from "@/components/employee/dashboard/WeekMiniView";
import type {
  EmployeeAppointmentRow,
  EmployeeEmergencyRow,
  UiAppointmentStatus,
  WeekDayCountRow,
} from "@/data/employee-appointments";
import { formatScheduleHeading, isTodayIso } from "@/lib/calendar";
import { fetchEmployeeSchedule, type EmployeeScheduleApiResponse } from "@/lib/employeeScheduleApi";
import { cn } from "@/lib/utils";

function normalizeUiStatus(s: string): UiAppointmentStatus {
  if (
    s === "confirmed" ||
    s === "arrived" ||
    s === "in-progress" ||
    s === "completed" ||
    s === "cancelled"
  ) {
    return s;
  }
  return "confirmed";
}

function mapResponse(data: EmployeeScheduleApiResponse): {
  appointments: EmployeeAppointmentRow[];
  emergencies: EmployeeEmergencyRow[];
  weekDays: WeekDayCountRow[];
  selectedDate: string;
  providerCount: number;
} {
  return {
    appointments: data.appointments.map((a) => ({
      id: a.id,
      patientName: a.patient_name,
      type: a.appointment_type_display,
      appointmentTypeCode: a.appointment_type_code,
      time: a.time_start,
      duration: a.duration_minutes,
      provider: a.provider_display_name ?? "—",
      uiStatus: normalizeUiStatus(a.ui_status),
      isEmergency: a.is_emergency,
    })),
    emergencies: data.emergency_alerts.map((e) => ({
      id: e.id,
      patientName: e.patient_name,
      description: e.description,
      time: e.time,
      severity: e.severity === "urgent" ? "urgent" : "critical",
    })),
    weekDays: data.week_day_counts.map((w) => ({
      day: w.day,
      count: w.count,
      date: typeof w.date === "string" ? w.date : String(w.date),
    })),
    selectedDate: typeof data.date === "string" ? data.date : String(data.date),
    providerCount: data.provider_count,
  };
}

export default function EmployeeDashboard() {
  const [appointments, setAppointments] = useState<EmployeeAppointmentRow[]>([]);
  const [emergencies, setEmergencies] = useState<EmployeeEmergencyRow[]>([]);
  const [weekDays, setWeekDays] = useState<WeekDayCountRow[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [providerCount, setProviderCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstLoad = useRef(true);

  const load = useCallback(async (dateIso?: string) => {
    if (firstLoad.current) {
      setLoading(true);
    } else {
      setPending(true);
    }
    setError(null);
    try {
      const raw = await fetchEmployeeSchedule(dateIso);
      const m = mapResponse(raw);
      setAppointments(m.appointments);
      setEmergencies(m.emergencies);
      setWeekDays(m.weekDays);
      setSelectedDate(m.selectedDate);
      setProviderCount(m.providerCount);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load schedule");
      if (firstLoad.current) {
        setAppointments([]);
        setEmergencies([]);
        setWeekDays([]);
        setSelectedDate("");
        setProviderCount(0);
      }
    } finally {
      setLoading(false);
      setPending(false);
      firstLoad.current = false;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectDate = useCallback((isoDate: string) => {
    void load(isoDate);
  }, [load]);

  const heading = selectedDate ? formatScheduleHeading(selectedDate) : "Schedule";
  const sub = selectedDate
    ? `${isTodayIso(selectedDate) ? "Today" : "Selected day"} · ${appointments.length} appointment${appointments.length === 1 ? "" : "s"}`
    : "";

  return (
    <div className="min-h-full bg-background">
      <DashboardHeader emergencies={emergencies} />
      <EmergencyBanner alerts={emergencies} />

      <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6">
        {error && (
          <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <p className="font-medium">Could not load schedule</p>
            <p className="mt-1 text-destructive/90">{error}</p>
            <button
              type="button"
              onClick={() => void load(selectedDate || undefined)}
              className="mt-2 text-xs font-medium underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <p className="py-12 text-center text-sm text-muted-foreground">Loading schedule…</p>
        ) : (
          <div
            className={cn(
              "flex flex-col gap-5 lg:flex-row",
              pending && "pointer-events-none opacity-60",
            )}
          >
            <div className="min-w-0 flex-1">
              <div className="mb-4">
                <h2 className="font-display text-lg font-semibold text-foreground">{heading}</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
              </div>

              <ScheduleDateNav
                selectedDate={selectedDate}
                weekDays={weekDays}
                onSelectDate={selectDate}
                disabled={pending}
              />

              <div className="space-y-4">
                <WeekMiniView
                  weekDays={weekDays}
                  selectedDate={selectedDate}
                  onSelectDate={selectDate}
                />
                <DaySchedule appointments={appointments} />
              </div>
            </div>

            <div className="w-full flex-shrink-0 lg:w-80">
              <SidePanel
                appointments={appointments}
                weekDays={weekDays}
                selectedDate={selectedDate}
                providerCount={providerCount}
                onSelectDate={selectDate}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
