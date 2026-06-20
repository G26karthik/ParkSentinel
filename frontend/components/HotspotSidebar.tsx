"use client";

import Link from "next/link";
import { H3Feature, cisHex } from "@/lib/api";
import {
  LineChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";

interface HotspotSidebarProps {
  feature: H3Feature | null;
  onClose: () => void;
}

const SHIFT_LABEL: Record<number, string> = {
  7: "Weekday mornings 7–9am",
  8: "Weekday mornings 8–10am",
  9: "Weekday mornings 8–10am",
  10: "Late morning 10am–12pm",
  17: "Evening rush 5–7pm",
  18: "Evening rush 5–7pm",
  19: "Evening 7–9pm",
  20: "Evening 7–9pm",
};

function officersFor(classification: string): number {
  return { CRITICAL: 3, HIGH: 2, MODERATE: 1 }[classification] || 1;
}

export default function HotspotSidebar({ feature, onClose }: HotspotSidebarProps) {
  if (!feature) return null;

  const p = feature.properties;
  const monthly = p.monthly_counts || {};
  const sparkData = Object.entries(monthly)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-6)
    .map(([month, count]) => ({ month: month.slice(5), count }));

  const peakLabel = SHIFT_LABEL[p.peak_hour || 10] || `Hour ${p.peak_hour}:00`;

  return (
    <div className="absolute right-4 top-20 bottom-4 w-80 bg-gray-900/95 backdrop-blur border border-gray-700 rounded-xl overflow-y-auto shadow-2xl z-10">
      <div className="p-4 border-b border-gray-800 flex justify-between items-start">
        <div>
          <p className="text-xs text-gray-400">Zone</p>
          <h2 className="text-lg font-semibold text-white leading-tight">
            {p.is_junction_cell ? "Junction Hotspot" : "Parking Hotspot"}
          </h2>
          <p className="text-xs text-gray-500 mt-1 font-mono">{p.h3_cell}</p>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">
          ×
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div className="flex items-center gap-3">
          <div
            className="text-4xl font-bold"
            style={{ color: cisHex(p.classification) }}
          >
            {p.cis.toFixed(0)}
          </div>
          <span
            className="px-2 py-1 rounded text-xs font-bold text-white"
            style={{ backgroundColor: cisHex(p.classification) }}
          >
            {p.classification}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-gray-400 text-xs">Violations</p>
            <p className="text-white font-semibold text-lg">{p.violation_count}</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-gray-400 text-xs">Vehicles</p>
            <p className="text-white font-semibold text-lg">{p.unique_vehicles || "—"}</p>
          </div>
        </div>

        <div className="text-sm space-y-1">
          <p>
            <span className="text-gray-400">Vehicle: </span>
            <span className="text-white">{p.dominant_vehicle_type || "—"}</span>
          </p>
          <p>
            <span className="text-gray-400">Violation: </span>
            <span className="text-white">{p.dominant_violation_type || "—"}</span>
          </p>
          <p>
            <span className="text-gray-400">Peak time: </span>
            <span className="text-white">{peakLabel}</span>
          </p>
        </div>

        <div className="bg-red-900/30 border border-red-800/50 rounded-lg p-3 text-sm">
          <p className="text-red-300 font-medium">Enforcement Recommendation</p>
          <p className="text-white mt-1">
            Deploy <strong>{officersFor(p.classification)} officers</strong> during peak hours
          </p>
        </div>

        {sparkData.length > 0 && (
          <div>
            <p className="text-xs text-gray-400 mb-2">Monthly Trend</p>
            <ResponsiveContainer width="100%" height={80}>
              <LineChart data={sparkData}>
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <YAxis hide />
                <Tooltip
                  contentStyle={{ background: "#1f2937", border: "none", fontSize: 12 }}
                />
                <Line type="monotone" dataKey="count" stroke="#ef4444" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <Link
            href={`/forecast?cell=${p.h3_cell}`}
            className="block text-center bg-gray-800 hover:bg-gray-700 text-white text-sm py-2 rounded-lg transition-colors"
          >
            View Forecast →
          </Link>
          <Link
            href="/enforcement"
            className="block text-center bg-red-600 hover:bg-red-500 text-white text-sm py-2 rounded-lg transition-colors"
          >
            Add to Enforcement Plan →
          </Link>
        </div>
      </div>
    </div>
  );
}
