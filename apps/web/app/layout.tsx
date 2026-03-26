import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dental Chatbot",
  description: "Dental office assistant chat (skeleton)",
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
