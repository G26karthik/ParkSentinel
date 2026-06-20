"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import StatCard from "@/components/StatCard";
import TimeFilter from "@/components/TimeFilter";
import LayerToggle from "@/components/LayerToggle";
import HotspotSidebar from "@/components/HotspotSidebar";
import AnomalyBanner from "@/components/AnomalyBanner";
import {
  getSummaryStats,
  getH3Grid,
  getHeatmapData,
  getTopJunctions,
  getAnomalies,
  H3Feature,
  SummaryStats,
  AnomalyRecord,
} from "@/lib/api";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export default function DashboardPage() {
  const [stats, setStats] = useState<SummaryStats | null>(null);
  const [h3Data, setH3Data] = useState<H3Feature[]>([]);
  const [heatmapPoints, setHeatmapPoints] = useState<{ lat: number; lon: number; weight: number }[]>([]);
  const [junctions, setJunctions] = useState<{ junction_name: string; violation_count: number; lat: number; lon: number }[]>([]);
  const [anomalies, setAnomalies] = useState<AnomalyRecord[]>([]);
  const [month, setMonth] = useState("");
  const [layerMode, setLayerMode] = useState<"hex" | "heatmap" | "both">("hex");
  const [selected, setSelected] = useState<H3Feature | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [s, h3, heat, jun, anom] = await Promise.all([
        getSummaryStats(),
        getH3Grid(month || undefined),
        getHeatmapData(month || undefined),
        getTopJunctions(),
        getAnomalies(),
      ]);
      setStats(s);
      setH3Data(h3.features);
      setHeatmapPoints(heat.points);
      setJunctions(jun);
      setAnomalies(anom.anomalies);
    } catch (e) {
      console.error("Failed to load dashboard data", e);
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="relative h-full">
      {/* Header overlay */}
      <div className="absolute top-0 left-0 right-0 z-20 p-4 space-y-3 pointer-events-none">
        <div className="flex flex-col md:flex-row items-start gap-3 pointer-events-auto w-full max-w-full">
          <div className="flex flex-row overflow-x-auto snap-x no-scrollbar gap-2 flex-1 w-full md:w-auto md:flex-wrap pb-2 md:pb-0 [&>*]:shrink-0 [&>*]:snap-start">
            {stats && (
              <>
                <StatCard
                  label="Validated Violations"
                  value={stats.total_approved.toLocaleString()}
                />
                <StatCard
                  label="Critical Zones"
                  value={stats.critical_zones_count}
                  sub="CIS ≥ 62"
                />
                <StatCard
                  label="Peak Hour"
                  value={stats.peak_hour_citywide !== null ? `${stats.peak_hour_citywide}:00` : "—"}
                />
                <StatCard
                  label="Most Active Zone"
                  value={stats.most_active_station || "—"}
                />
              </>
            )}
          </div>
          <div className="flex gap-2 w-full md:w-auto overflow-x-auto items-center">
            <TimeFilter month={month} onChange={setMonth} />
            <LayerToggle mode={layerMode} onChange={setLayerMode} />
            <div className="hidden lg:flex items-center gap-2 bg-gray-900/90 border border-gray-700 rounded-lg px-3 py-2 text-[10px] font-bold uppercase tracking-wider backdrop-blur text-gray-400 select-none shrink-0">
              Designed for ASTRAM/BTP integration (not yet connected)
            </div>
          </div>
        </div>
        <div className="pointer-events-auto space-y-2">
          <AnomalyBanner anomalies={anomalies} selectedMonth={month} />
          {(month === "2024-02" || month === "2024-03") && (
            <div className="bg-yellow-600/20 border border-yellow-600/50 text-yellow-200 px-4 py-2.5 rounded-lg text-xs md:text-sm max-w-xl backdrop-blur">
              ⚠️ <strong>Data Validation Backlog:</strong> {month === "2024-02" ? "February 2024" : "March 2024"} has an administrative backlog (only {month === "2024-02" ? "1,719" : "7,038"} approved of {month === "2024-02" ? "54,660" : "55,455"} raw records). Trend drops are reporting anomalies, not a physical decline.
            </div>
          )}
        </div>
      </div>

      {/* Map */}
      <div className="h-full w-full">
        {loading ? (
          <div className="flex items-center justify-center h-full bg-gray-950">
            <div className="text-center">
              <div className="animate-spin w-10 h-10 border-2 border-red-500 border-t-transparent rounded-full mx-auto" />
              <p className="text-gray-400 mt-4 text-sm">Loading Bengaluru parking intelligence...</p>
            </div>
          </div>
        ) : (
          <MapView
            h3Data={h3Data}
            heatmapPoints={heatmapPoints}
            junctions={junctions}
            layerMode={layerMode}
            onSelect={setSelected}
          />
        )}
      </div>

      <HotspotSidebar feature={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
