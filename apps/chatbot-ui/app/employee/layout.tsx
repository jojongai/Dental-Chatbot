import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Employee — Bright Smile Dental",
  description: "Front desk schedule dashboard",
};

export default function EmployeeLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] overflow-y-auto overflow-x-hidden bg-background">
      {children}
    </div>
  );
}
