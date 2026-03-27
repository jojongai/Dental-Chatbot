"use client";

import { AlertTriangle, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import type { EmployeeEmergencyRow } from "@/data/employee-appointments";

interface EmergencyBannerProps {
  alerts: EmployeeEmergencyRow[];
}

const EmergencyBanner = ({ alerts }: EmergencyBannerProps) => {
  const [dismissed, setDismissed] = useState<string[]>([]);
  const visible = alerts.filter((a) => !dismissed.includes(a.id));

  if (alerts.length === 0) return null;

  return (
    <div id="emergency-banner-region" className="mx-4 mt-4 space-y-4 sm:mx-6">
      <AnimatePresence>
        {visible.map((alert) => (
          <motion.div
            key={alert.id}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="rounded-xl border-2 border-emergency/30 bg-emergency-light px-4 py-3 shadow-md"
          >
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-emergency/10">
              <AlertTriangle className="h-4 w-4 text-emergency" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-0.5 flex items-center gap-2">
                <span className="font-display text-sm font-semibold text-emergency-foreground">
                  Emergency — {alert.patientName}
                </span>
                <span className="rounded-md bg-emergency px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-primary-foreground">
                  {alert.severity}
                </span>
              </div>
              <p className="text-sm text-emergency-foreground/80">{alert.description}</p>
              <p className="mt-1 text-xs text-emergency-foreground/60">Reported at {alert.time}</p>
            </div>
            <button
              type="button"
              onClick={() => setDismissed((d) => [...d, alert.id])}
              className="flex-shrink-0 rounded-md p-1 transition-colors hover:bg-emergency/10"
            >
              <X className="h-4 w-4 text-emergency-foreground/60" />
            </button>
          </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

export default EmergencyBanner;
