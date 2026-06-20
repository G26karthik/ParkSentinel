"use client";

import { AnomalyRecord } from "@/lib/api";

interface AnomalyBannerProps {
  anomalies: AnomalyRecord[];
  selectedMonth: string;
}

export default function AnomalyBanner({ anomalies, selectedMonth }: AnomalyBannerProps) {
  if (!selectedMonth || anomalies.length === 0) return null;

  const monthAnomalies = anomalies.filter((a) => a.date.startsWith(selectedMonth));
  if (monthAnomalies.length === 0) return null;

  const top = monthAnomalies.sort((a, b) => b.total_violations - a.total_violations)[0];
  const dateLabel = new Date(top.date).toLocaleDateString("en-IN", {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="bg-yellow-600/20 border border-yellow-600/50 text-yellow-200 px-4 py-2 rounded-lg text-sm">
      ⚠️ Unusual spike detected on {dateLabel} — {top.likely_cause.toLowerCase()}.
      {top.affected_zones.length > 0 && (
        <span className="ml-1">Zones: {top.affected_zones.slice(0, 3).join(", ")}</span>
      )}
    </div>
  );
}
