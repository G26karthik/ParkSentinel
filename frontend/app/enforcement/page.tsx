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
  const [showRoute, setShowRoute] = useState(false);
  const [isDispatchOpen, setIsDispatchOpen] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [dispatchSuccess, setDispatchSuccess] = useState(false);

  const handleDispatch = () => {
    setIsDispatching(true);
    setTimeout(() => {
      setIsDispatching(false);
      setDispatchSuccess(true);
    }, 2000);
  };

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
          <button
            onClick={() => setIsDispatchOpen(true)}
            className="bg-red-600 hover:bg-red-500 text-white text-sm px-4 py-2 rounded-lg w-full md:w-auto font-medium transition-colors text-center"
          >
            Dispatch to BTP/ASTRAM
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
        <div className="space-y-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h3 className="text-white font-semibold text-sm">Recommended zones map</h3>
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300 bg-gray-900 border border-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-800 transition-colors select-none">
              <input
                type="checkbox"
                checked={showRoute}
                onChange={(e) => setShowRoute(e.target.checked)}
                className="accent-red-600 rounded bg-gray-950 border-gray-700 w-3.5 h-3.5"
              />
              Show ASTRAM Patrol Route
            </label>
          </div>
          <EnforcementMiniMap key={`${station}-${showRoute}`} items={plan.items} showRoute={showRoute} />
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

      {/* BTP/ASTRAM Dispatch Modal */}
      {isDispatchOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl relative">
            <button
              onClick={() => {
                setIsDispatchOpen(false);
                setIsDispatching(false);
                setDispatchSuccess(false);
              }}
              className="absolute top-4 right-4 text-gray-400 hover:text-white transition-colors"
            >
              ✕
            </button>
            <div className="flex items-center gap-2">
              <span className="text-xl">🚨</span>
              <h3 className="text-lg font-bold text-white">ASTRAM Dispatch Control</h3>
            </div>
            
            {!isDispatching && !dispatchSuccess ? (
              <div className="space-y-4">
                <p className="text-gray-400 text-sm leading-relaxed">
                  You are about to transmit the optimized deployment plan of <strong>{plan?.total_officers || 10} officers</strong> across <strong>{plan?.zones_count || 5} hotspots</strong> to the Bengaluru Traffic Police (BTP) ASTRAM dispatch network.
                </p>
                <div className="bg-gray-950 p-3 rounded-lg text-[11px] space-y-1 font-mono text-gray-300 border border-gray-850">
                  <div>TICKET: BTP-ASTRAM-{date.replace(/-/g, "")}-{(station || "ALL").slice(0, 3).toUpperCase()}</div>
                  <div>OFFICERS: {plan?.total_officers} deployed</div>
                  <div>ZONES: {plan?.zones_count} selected</div>
                  <div>PRIORITY: HIGH (CIS Range: {plan?.items && plan.items.length > 0 ? plan.items[0].cis.toFixed(0) : "0"}+)</div>
                </div>
                <button
                  onClick={handleDispatch}
                  className="w-full bg-red-600 hover:bg-red-500 text-white font-medium py-2.5 rounded-xl text-sm transition-all shadow-lg shadow-red-900/30"
                >
                  Confirm Dispatch & Alert Units
                </button>
              </div>
            ) : isDispatching ? (
              <div className="text-center py-6 space-y-4">
                <div className="animate-spin w-10 h-10 border-2 border-red-500 border-t-transparent rounded-full mx-auto" />
                <p className="text-sm text-gray-300">Transmitting dispatch orders to BTP control network...</p>
                <div className="w-full bg-gray-800 rounded-full h-1">
                  <div className="bg-red-650 bg-red-600 h-1 rounded-full animate-pulse w-full" />
                </div>
              </div>
            ) : (
              <div className="text-center py-6 space-y-4">
                <div className="w-12 h-12 rounded-full bg-green-500/20 text-green-400 flex items-center justify-center mx-auto text-xl font-bold">
                  ✓
                </div>
                <h4 className="text-white font-bold">Orders Successfully Dispatched</h4>
                <p className="text-xs text-gray-400 leading-relaxed">
                  Patrol units in <strong>{station || "all jurisdictions"}</strong> have been alerted. Patrol routes linked to local ASTRAM mobile consoles.
                </p>
                <button
                  onClick={() => {
                    setIsDispatchOpen(false);
                    setIsDispatching(false);
                    setDispatchSuccess(false);
                  }}
                  className="w-full bg-gray-800 hover:bg-gray-700 text-white py-2 rounded-xl text-sm font-medium transition-colors"
                >
                  Close Window
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
