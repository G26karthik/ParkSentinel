"use client";

import { EnforcementItem, cisHex } from "@/lib/api";

interface EnforcementCardProps {
  item: EnforcementItem;
}

const TREND_ICON = { improving: "↓", worsening: "↑", stable: "→" };

export default function EnforcementCard({ item }: EnforcementCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <span className="text-xs text-gray-500">#{item.rank}</span>
          <h3 className="text-white font-semibold">{item.zone_name}</h3>
          <p className="text-xs text-gray-400">{item.police_station}</p>
        </div>
        <div className="text-right">
          <span
            className="text-2xl font-bold"
            style={{ color: cisHex(item.classification) }}
          >
            {item.cis.toFixed(0)}
          </span>
          <p className="text-xs" style={{ color: cisHex(item.classification) }}>
            {item.classification}
          </p>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-gray-500">Officers</p>
          <p className="text-white font-medium">{item.recommended_officers}</p>
        </div>
        <div>
          <p className="text-gray-500">Shift</p>
          <p className="text-white font-medium">{item.recommended_shift.split(" ")[0]}</p>
        </div>
        <div>
          <p className="text-gray-500">Trend</p>
          <p className="text-white font-medium">
            {TREND_ICON[item.trend as keyof typeof TREND_ICON] || "→"} {item.trend}
          </p>
        </div>
      </div>
    </div>
  );
}
