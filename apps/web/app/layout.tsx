import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Maya — Bright Smile Dental",
  description: "Missed-call SMS assistant for Bright Smile Dental",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased font-sans">{children}</body>
    </html>
  );
}
