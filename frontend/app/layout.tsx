import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "ParkSentinel — Bengaluru Parking Intelligence",
  description: "AI-powered parking enforcement intelligence for Bengaluru",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-gray-950 text-gray-100 antialiased">
        <div className="flex flex-col md:flex-row h-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 min-h-0 overflow-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
