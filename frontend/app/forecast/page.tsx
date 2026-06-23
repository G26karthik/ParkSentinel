"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ForecastChart from "@/components/ForecastChart";
import { getTopForecasts, getForecast, getSummaryByStation, getH3Grid } from "@/lib/api";

const TIMEOUT_MS = 15000;

interface ForecastEntry {
  h3_cell: string;
  forecast: unknown[];
  historical: unknown[];
  zone_name?: string;
}

interface ZoneCell {
  h3_cell: string;
  police_station: string;
  zone_name?: string;
}

function ForecastContent() {
  const searchParams = useSearchParams();
  const cellParam = searchParams.get("cell");
  const stationUrlParam = searchParams.get("station") || "";

  // Forecast cache: only top-N cells with pre-trained Prophet models
  const [forecastCache, setForecastCache] = useState<ForecastEntry[]>([]);
  // Current chart data (fetched on-demand for selected cell)
  const [currentForecast, setCurrentForecast] = useState<ForecastEntry | null>(null);
  const [fetchingForecast, setFetchingForecast] = useState(false);
  const [noForecastForCell, setNoForecastForCell] = useState(false);

  // All h3 zones grouped by station
  const [zonesByStation, setZonesByStation] = useState<Record<string, ZoneCell[]>>({});
  const [allStations, setAllStations] = useState<string[]>([]);

  const [stationFilter, setStationFilter] = useState<string>(stationUrlParam);
  const [selected, setSelected] = useState<string>("");

  const [loading, setLoading] = useState(true);
  const [timedOut, setTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Load forecast cache + h3-grid zones + stations in parallel
  const load = useCallback(async () => {
    setLoading(true);
    setTimedOut(false);
    setError(null);

    const timer = setTimeout(() => setTimedOut(true), TIMEOUT_MS);

    try {
      const [topData, h3Data, stationData] = await Promise.allSettled([
        getTopForecasts(),
        getH3Grid(),
        getSummaryByStation(),
      ]);

      clearTimeout(timer);

      const forecasts: ForecastEntry[] =
        topData.status === "fulfilled" ? topData.value.forecasts : [];
      setForecastCache(forecasts);

      // Build station → cells map from h3-grid
      const byStation: Record<string, ZoneCell[]> = {};
      if (h3Data.status === "fulfilled") {
        for (const feat of h3Data.value.features) {
          const ps = feat.properties.police_station || "";
          const zn = feat.properties.zone_name || ps || feat.properties.h3_cell;
          if (!ps) continue; // skip cells without a station (backend not yet restarted)
          if (!byStation[ps]) byStation[ps] = [];
          byStation[ps].push({ h3_cell: feat.properties.h3_cell, police_station: ps, zone_name: zn });
        }
      }

      // If h3-grid has police_station data → use it; else fall back to forecast cache grouping
      const hasStationData = Object.keys(byStation).length > 0;
      if (!hasStationData && forecasts.length > 0) {
        // Fallback: derive stations + zones from top-forecast zone_names like "Upparpet (b55)"
        for (const f of forecasts) {
          const stationName = f.zone_name?.replace(/\s*\([^)]+\)$/, "").trim() || "Unknown";
          if (!byStation[stationName]) byStation[stationName] = [];
          byStation[stationName].push({
            h3_cell: f.h3_cell,
            police_station: stationName,
            zone_name: f.zone_name,
          });
        }
      }
      setZonesByStation(byStation);

      // Stations: from API if available, else from map keys
      const stations: string[] =
        stationData.status === "fulfilled"
          ? stationData.value.map((r) => r.police_station).filter(Boolean).sort()
          : Object.keys(byStation).sort();
      setAllStations(stations);

      // Determine initial station + cell selection
      let initStation = stationUrlParam;
      let initCell = cellParam || "";

      if (cellParam) {
        // Find station for this cell
        const cellInCache = forecasts.find((f) => f.h3_cell === cellParam);
        if (cellInCache) {
          // Cell is in top forecasts — find its station
          const cellStation = cellInCache.zone_name?.replace(/\s*\([^)]+\)$/, "").trim() || stationUrlParam;
          if (!initStation) initStation = cellStation;
        } else {
          // Cell not in forecasts — use station from URL if provided
          if (!initStation) initStation = stationUrlParam;
        }
      }

      if (!initStation && stations.length > 0) initStation = stations[0];
      setStationFilter(initStation);

      // Pick zone to display
      if (cellParam) {
        initCell = cellParam;
      } else {
        const zonesForStation = byStation[initStation] || [];
        // Prefer a zone that has a forecast in cache
        const withForecast = zonesForStation.find((z) =>
          forecasts.some((f) => f.h3_cell === z.h3_cell)
        );
        initCell = withForecast?.h3_cell || zonesForStation[0]?.h3_cell || forecasts[0]?.h3_cell || "";
      }
      setSelected(initCell);
    } catch (e) {
      clearTimeout(timer);
      setError("Could not reach the forecast API. Make sure the backend is running.");
      console.error(e);
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }, [cellParam, stationUrlParam, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  // Fetch forecast for selected cell whenever it changes
  useEffect(() => {
    if (!selected) return;
    const cached = forecastCache.find((f) => f.h3_cell === selected);
    if (cached) {
      setCurrentForecast(cached);
      setNoForecastForCell(false);
      return;
    }
    // Not in cache — try individual fetch
    setFetchingForecast(true);
    setNoForecastForCell(false);
    setCurrentForecast(null);
    getForecast(selected)
      .then((f) => {
        if (f.forecast?.length) {
          setCurrentForecast(f as ForecastEntry);
        } else {
          setNoForecastForCell(true);
        }
      })
      .catch(() => setNoForecastForCell(true))
      .finally(() => setFetchingForecast(false));
  }, [selected, forecastCache]);

  const zonesForStation = stationFilter ? (zonesByStation[stationFilter] || []) : [];
  const visibleZones = zonesForStation.length > 0
    ? zonesForStation
    : forecastCache.map((f) => ({ h3_cell: f.h3_cell, police_station: "", zone_name: f.zone_name }));

  const topRiskDays = currentForecast
    ? (currentForecast.forecast as { ds: string; yhat: number }[])
        .map((f) => ({ date: f.ds, predicted: Math.round(f.yhat) }))
        .sort((a, b) => b.predicted - a.predicted)
        .slice(0, 5)
    : [];

  if (loading) {
    return (
      <div className="p-8 space-y-6 w-full h-full overflow-y-auto">
        <div>
          <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
          <p className="text-gray-400 text-sm mt-1">14-day prediction per zone</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 space-y-4">
          <div className="flex items-center gap-3 text-gray-300">
            <div className="animate-spin w-5 h-5 border-2 border-red-500 border-t-transparent rounded-full shrink-0" />
            <span className="text-sm font-medium">Loading forecast models…</span>
          </div>
          {timedOut && (
            <div className="bg-yellow-900/20 border border-yellow-700/40 rounded-lg p-4 space-y-2">
              <p className="text-yellow-300 text-sm font-medium">⏳ Taking longer than usual</p>
              <p className="text-yellow-200/70 text-xs leading-relaxed">
                On first startup the system trains prediction models for critical zones —
                this takes <strong>60–90 seconds</strong> and is then cached. Please wait.
              </p>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 space-y-4 w-full h-full overflow-y-auto">
        <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
        <div className="bg-red-900/20 border border-red-800/50 rounded-xl p-6 space-y-3">
          <p className="text-red-300 text-sm font-medium">⚠ Backend Unreachable</p>
          <p className="text-gray-400 text-sm">{error}</p>
          <button onClick={() => setAttempt((a) => a + 1)} className="bg-red-700 hover:bg-red-600 text-white text-sm px-4 py-2 rounded-lg transition-colors">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const selectedZone = visibleZones.find((z) => z.h3_cell === selected);
  const zoneDisplayName = selectedZone?.zone_name
    || currentForecast?.zone_name
    || (stationFilter ? `${stationFilter} Zone` : selected);

  return (
    <div className="p-6 space-y-6 w-full h-full overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
        <p className="text-gray-400 text-sm mt-1">
          14-day AI prediction · browse by station and zone
        </p>
      </div>

      {/* Two-level selector: station → zone */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">Police Station</label>
          <select
            value={stationFilter}
            onChange={(e) => {
              const s = e.target.value;
              setStationFilter(s);
              // Auto-select first zone in new station
              const zones = zonesByStation[s] || [];
              const withForecast = zones.find((z) =>
                forecastCache.some((f) => f.h3_cell === z.h3_cell)
              );
              const first = withForecast || zones[0];
              if (first) setSelected(first.h3_cell);
              else setSelected(forecastCache[0]?.h3_cell || "");
            }}
            className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm w-full sm:w-56"
          >
            <option value="">All stations</option>
            {allStations.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1 flex-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">
            Zone ({visibleZones.length} available{stationFilter ? ` in ${stationFilter}` : ""})
          </label>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm w-full"
          >
            {visibleZones.length === 0 ? (
              <option value="">No zones available</option>
            ) : (
              visibleZones.map((z) => (
                <option key={z.h3_cell} value={z.h3_cell}>
                  {z.zone_name || z.h3_cell}
                  {forecastCache.some((f) => f.h3_cell === z.h3_cell) ? "" : " (forecast loading)"}
                </option>
              ))
            )}
          </select>
        </div>
      </div>

      {/* Empty state for selected station */}
      {stationFilter && zonesForStation.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center space-y-2">
          <p className="text-gray-300 font-medium">No zones loaded for {stationFilter}</p>
          <p className="text-gray-500 text-sm">
            Zone data is loading from the backend. Make sure the backend is running and try refreshing.
          </p>
        </div>
      )}

      {/* Chart area */}
      {fetchingForecast && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 flex items-center gap-3">
          <div className="animate-spin w-4 h-4 border-2 border-red-500 border-t-transparent rounded-full shrink-0" />
          <span className="text-gray-400 text-sm">Loading forecast for {zoneDisplayName}…</span>
        </div>
      )}

      {noForecastForCell && !fetchingForecast && (
        <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-xl p-5 space-y-2">
          <p className="text-yellow-300 font-medium text-sm">No detailed forecast for this zone yet</p>
          <p className="text-gray-400 text-xs leading-relaxed">
            <strong>{zoneDisplayName}</strong> doesn't have a trained prediction model yet.
            Detailed forecasts are computed for the top 20 highest-risk zones citywide.
            Select a zone marked without "(forecast loading)" for instant results.
          </p>
        </div>
      )}

      {currentForecast && !fetchingForecast && (
        <ForecastChart
          title={zoneDisplayName}
          historical={currentForecast.historical as { ds: string; y: number }[]}
          forecast={currentForecast.forecast as { ds: string; yhat: number; yhat_lower: number; yhat_upper: number }[]}
        />
      )}

      {topRiskDays.length > 0 && !fetchingForecast && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="text-white font-semibold mb-3">Top 5 Predicted High-Risk Days</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-left">
                <th className="pb-2">Date</th>
                <th className="pb-2">Expected Violations</th>
              </tr>
            </thead>
            <tbody>
              {topRiskDays.map((d) => (
                <tr key={d.date} className="border-t border-gray-800">
                  <td className="py-2 text-white">
                    {new Date(d.date).toLocaleDateString("en-IN", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                    })}
                  </td>
                  <td className="py-2 text-red-400 font-medium">{d.predicted}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-gray-400 text-xs mt-4">
            <strong>{zoneDisplayName}</strong> is predicted to peak on these days — consider pre-emptive deployment.
          </p>
        </div>
      )}
    </div>
  );
}

export default function ForecastPage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-400">Loading...</div>}>
      <ForecastContent />
    </Suspense>
  );
}
