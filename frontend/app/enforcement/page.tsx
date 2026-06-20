"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { getEnforcementPlan, getSummaryByStation, EnforcementItem, cisHex } from "@/lib/api";

const EnforcementMiniMap = dynamic(() => import("@/components/EnforcementMiniMap"), { ssr: false });

const TREND_ICON = { improving: "↓", worsening: "↑", stable: "→" };

export default function EnforcementPage() {
  const [plan, setPlan] = useState<{
    date: string;
    total_officers: number;
    zones_count: number;
    items: EnforcementItem[];
  } | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [station, setStation] = useState("");
  const [stations, setStations] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSummaryByStation()
      .then((rows) =>
        setStations(rows.map((r) => r.police_station).filter(Boolean).sort())
      )
      .catch((e) => console.error(e));
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const data = await getEnforcementPlan(date, station || undefined);
        setPlan(data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [date, station]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Enforcement Plan</h1>
          <p className="text-gray-400 text-sm mt-1">
            Data-driven deployment recommendations for Bengaluru Traffic Police
          </p>
        </div>
        <div className="flex flex-col md:flex-row gap-3 w-full md:w-auto">
          <select
            value={station}
            onChange={(e) => setStation(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm w-full md:max-w-[16rem]"
          >
            <option value="">All police stations</option>
            {stations.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm w-full md:w-auto"
          />
          <button
            onClick={() => window.print()}
            className="bg-gray-800 hover:bg-gray-700 text-white text-sm px-4 py-2 rounded-lg w-full md:w-auto"
          >
            Export as PDF
          </button>
        </div>
      </div>

      {plan && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-xl px-4 py-3 text-sm text-red-200">
          Total officers recommended: <strong>{plan.total_officers}</strong> across{" "}
          <strong>{plan.zones_count}</strong> zones
          {station && <> · filtered to <strong>{station}</strong></>}
        </div>
      )}

      {plan && plan.items.length > 0 && (
        <div>
          <h3 className="text-white font-semibold mb-2 text-sm">Recommended zones map</h3>
          <EnforcementMiniMap key={station || "all"} items={plan.items} />
        </div>
      )}

      {loading ? (
        <div className="text-gray-400">Generating enforcement plan...</div>
      ) : plan ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <thead className="bg-gray-800 text-gray-400 text-left">
              <tr>
                <th className="px-4 py-3">Rank</th>
                <th className="px-4 py-3">Zone</th>
                <th className="px-4 py-3">CIS</th>
                <th className="px-4 py-3">Violations</th>
                <th className="px-4 py-3">Officers</th>
                <th className="px-4 py-3">Shift</th>
                <th className="px-4 py-3">Dominant Type</th>
                <th className="px-4 py-3">Trend</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.map((item) => (
                <tr key={item.rank} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-4 py-3 text-gray-400">#{item.rank}</td>
                  <td className="px-4 py-3 text-white font-medium">{item.zone_name}</td>
                  <td className="px-4 py-3">
                    <span style={{ color: cisHex(item.classification) }} className="font-bold">
                      {item.cis.toFixed(0)}
                    </span>
                    <span className="text-xs ml-1 text-gray-500">{item.classification}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{item.total_violations}</td>
                  <td className="px-4 py-3 text-white font-medium">{item.recommended_officers}</td>
                  <td className="px-4 py-3 text-gray-300">{item.recommended_shift}</td>
                  <td className="px-4 py-3 text-gray-300">
                    {item.dominant_vehicle} / {item.dominant_violation}
                  </td>
                  <td className="px-4 py-3">
                    {TREND_ICON[item.trend as keyof typeof TREND_ICON]} {item.trend}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
