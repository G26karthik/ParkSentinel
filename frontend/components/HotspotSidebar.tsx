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

  const peakLabel = SHIFT_LABEL[p.peak_hour || 10] || `Around ${p.peak_hour}:00`;
  const officers = officersFor(p.classification);
  const station = p.police_station || "";
  // h3_cell[-8:-5] gives 3-char unique suffix like "b55" even when backend hasn't sent zone_name yet
  const zoneId = p.h3_cell.slice(-8, -5).toUpperCase();
  const zoneName = p.zone_name || station
    ? `${p.zone_name || station}${p.zone_name ? "" : ` (${zoneId})`}`
    : `Zone ${zoneId}`;

  return (
    <div className="absolute right-4 top-20 bottom-4 w-80 bg-[#0f1117] border border-gray-700/80 rounded-xl overflow-y-auto shadow-2xl z-10">
      {/* Header */}
      <div className="p-4 border-b border-gray-800 flex justify-between items-start">
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">
            {p.is_junction_cell ? "Junction Zone" : "Parking Zone"}
          </p>
          <h2 className="text-base font-semibold text-white leading-tight mt-0.5">
            {zoneName}
          </h2>
          {station && (
            <p className="text-xs text-gray-400 mt-0.5">{station} Police Station</p>
          )}
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none mt-0.5">
          ×
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Risk score */}
        <div className="flex items-center gap-3">
          <div className="text-4xl font-bold" style={{ color: cisHex(p.classification) }}>
            {p.cis.toFixed(0)}
          </div>
          <div>
            <span
              className="px-2 py-1 rounded text-xs font-bold text-white"
              style={{ backgroundColor: cisHex(p.classification) }}
            >
              {p.classification} RISK
            </span>
            <p className="text-[10px] text-gray-500 mt-1">Congestion Impact Score (0–100)</p>
          </div>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-gray-400 text-xs">Total Violations</p>
            <p className="text-white font-semibold text-lg">{p.violation_count.toLocaleString()}</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-gray-400 text-xs">Unique Vehicles</p>
            <p className="text-white font-semibold text-lg">{p.unique_vehicles?.toLocaleString() || "—"}</p>
          </div>
        </div>

        {/* Details */}
        <div className="text-sm space-y-1.5">
          <div className="flex justify-between">
            <span className="text-gray-400">Main vehicle type</span>
            <span className="text-white font-medium">{p.dominant_vehicle_type || "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Main violation</span>
            <span className="text-white font-medium">{p.dominant_violation_type || "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Busiest time</span>
            <span className="text-white font-medium">{peakLabel}</span>
          </div>
        </div>

        {/* Recommendation box */}
        <div className="bg-red-900/25 border border-red-800/50 rounded-lg p-3 text-sm">
          <p className="text-red-300 font-semibold text-xs uppercase tracking-wide mb-1.5">Recommended Action</p>
          <p className="text-white">
            Deploy <strong>{officers} officer{officers > 1 ? "s" : ""}</strong> during{" "}
            <strong>{peakLabel.toLowerCase()}</strong>
          </p>
        </div>

        {/* Trend sparkline */}
        {sparkData.length > 0 && (
          <div>
            <p className="text-xs text-gray-400 mb-2">Monthly Violation Trend</p>
            <ResponsiveContainer width="100%" height={80}>
              <LineChart data={sparkData}>
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <YAxis hide />
                <Tooltip contentStyle={{ background: "#1f2937", border: "none", fontSize: 12 }} />
                <Line type="monotone" dataKey="count" stroke="#ef4444" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-col gap-2 pt-1">
          <Link
            href={`/forecast?cell=${p.h3_cell}${station ? `&station=${encodeURIComponent(station)}` : ""}`}
            className="block text-center bg-gray-800 hover:bg-gray-700 text-white text-sm py-2.5 rounded-lg transition-colors font-medium"
          >
            View 14-Day Forecast for this Zone →
          </Link>
          <Link
            href={`/enforcement${station ? `?station=${encodeURIComponent(station)}` : ""}`}
            className="block text-center bg-red-700 hover:bg-red-600 text-white text-sm py-2.5 rounded-lg transition-colors font-medium"
          >
            See Enforcement Plan for this Area →
          </Link>
        </div>
      </div>
    </div>
  );
}
