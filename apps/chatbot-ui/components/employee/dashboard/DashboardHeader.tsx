"use client";

import { AlertTriangle, Bell, CalendarDays } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { EmployeeEmergencyRow } from "@/data/employee-appointments";
import { cn } from "@/lib/utils";

interface DashboardHeaderProps {
  emergencies: EmployeeEmergencyRow[];
}

const DashboardHeader = ({ emergencies }: DashboardHeaderProps) => {
  /** Set after mount so SSR and first client paint match (avoids server TZ vs browser TZ hydration mismatch). */
  const [formattedDate, setFormattedDate] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setFormattedDate(
      new Date().toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    );
  }, []);
  const containerRef = useRef<HTMLDivElement>(null);
  const emergencyCount = emergencies.length;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const scrollToEmergencies = () => {
    document.getElementById("emergency-banner-region")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    setOpen(false);
  };

  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-6 py-4 shadow-sm">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <span className="font-display text-sm font-bold text-primary-foreground">B+</span>
          </div>
          <div>
            <h1 className="font-display text-lg font-semibold leading-tight text-foreground">Bright Smile Dental</h1>
            <p className="text-xs text-muted-foreground">Employee Dashboard</p>
          </div>
        </div>
      </div>

      <div className="hidden min-h-[1.25rem] items-center gap-2 text-muted-foreground sm:flex">
        <CalendarDays className="h-4 w-4" />
        <span className="text-sm font-medium">{formattedDate || "\u00a0"}</span>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative" ref={containerRef}>
          <button
            type="button"
            aria-expanded={open}
            aria-haspopup="dialog"
            aria-label={
              emergencyCount > 0
                ? `${emergencyCount} emergency notification${emergencyCount === 1 ? "" : "s"}`
                : "Notifications — no emergencies today"
            }
            onClick={() => setOpen((o) => !o)}
            className={cn(
              "relative rounded-lg p-2 transition-colors hover:bg-muted",
              open && "bg-muted",
            )}
          >
            <Bell className="h-5 w-5 text-muted-foreground" />
            {emergencyCount > 0 && (
              <span className="animate-pulse-emergency absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-emergency px-0.5 text-[10px] font-bold text-primary-foreground">
                {emergencyCount}
              </span>
            )}
          </button>

          {open && (
            <div
              role="dialog"
              aria-label="Emergency notifications"
              className="absolute right-0 top-full z-50 mt-2 w-[min(100vw-2rem,20rem)] rounded-lg border border-border bg-card shadow-lg"
            >
              <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
                <AlertTriangle className="h-4 w-4 shrink-0 text-emergency" />
                <span className="font-display text-sm font-semibold text-foreground">Emergencies</span>
              </div>
              {emergencyCount === 0 ? (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No active emergencies for this day.
                </p>
              ) : (
                <ul className="max-h-72 overflow-y-auto py-1">
                  {emergencies.map((e) => (
                    <li
                      key={e.id}
                      className="border-b border-border/60 px-3 py-2.5 last:border-b-0"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-foreground">{e.patientName}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{e.description}</p>
                          <p className="mt-1 text-xs text-muted-foreground/80">{e.time}</p>
                        </div>
                        <span
                          className={cn(
                            "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground",
                            e.severity === "critical" ? "bg-emergency" : "bg-amber-600",
                          )}
                        >
                          {e.severity}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {emergencyCount > 0 && (
                <div className="border-t border-border px-2 py-2">
                  <button
                    type="button"
                    onClick={scrollToEmergencies}
                    className="w-full rounded-md py-2 text-center text-xs font-medium text-primary underline-offset-2 hover:underline"
                  >
                    View emergency banners
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2.5 border-l border-border pl-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-xs font-medium text-accent-foreground">
            JD
          </div>
          <div className="hidden md:block">
            <p className="text-sm font-medium leading-tight text-foreground">Jane Davis</p>
            <p className="text-xs text-muted-foreground">Front Desk</p>
          </div>
        </div>
      </div>
    </header>
  );
};

export default DashboardHeader;
