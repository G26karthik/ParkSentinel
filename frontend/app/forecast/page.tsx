"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ForecastChart from "@/components/ForecastChart";
import { getTopForecasts, getForecast } from "@/lib/api";

const TIMEOUT_MS = 15000; // 15 s — show "still computing" message after this

function ForecastContent() {
  const searchParams = useSearchParams();
  const cellParam = searchParams.get("cell");
  const [forecasts, setForecasts] = useState<
    { h3_cell: string; forecast: unknown[]; historical: unknown[]; zone_name?: string }[]
  >([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [timedOut, setTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setTimedOut(false);
    setError(null);

    // Show "still computing" hint after TIMEOUT_MS
    const timer = setTimeout(() => setTimedOut(true), TIMEOUT_MS);

    try {
      const data = await getTopForecasts();
      clearTimeout(timer);
      setForecasts(data.forecasts);
      if (cellParam && data.forecasts.some((f) => f.h3_cell === cellParam)) {
        setSelected(cellParam);
      } else if (data.forecasts.length > 0) {
        setSelected(data.forecasts[0].h3_cell);
      }
    } catch (e) {
      clearTimeout(timer);
      setError("Could not reach the forecast API. Make sure the backend is running.");
      console.error(e);
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }, [cellParam, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const current = forecasts.find((f) => f.h3_cell === selected);

  const topRiskDays = current
    ? (current.forecast as { ds: string; yhat: number }[])
        .map((f) => ({ date: f.ds, predicted: Math.round(f.yhat) }))
        .sort((a, b) => b.predicted - a.predicted)
        .slice(0, 5)
    : [];

  if (loading) {
    return (
      <div className="p-8 space-y-6 w-full h-full overflow-y-auto">
        <div>
          <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
          <p className="text-gray-400 text-sm mt-1">14-day Prophet forecast for top critical zones</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 space-y-4">
          <div className="flex items-center gap-3 text-gray-300">
            <div className="animate-spin w-5 h-5 border-2 border-red-500 border-t-transparent rounded-full shrink-0" />
            <span className="text-sm font-medium">Loading forecast models…</span>
          </div>
          {timedOut && (
            <div className="bg-yellow-900/20 border border-yellow-700/40 rounded-lg p-4 space-y-2">
              <p className="text-yellow-300 text-sm font-medium">⏳ This is taking longer than usual</p>
              <p className="text-yellow-200/70 text-xs leading-relaxed">
                On first startup, the backend trains Prophet time-series models for the top 20 critical zones — this can take <strong>60–90 seconds</strong>. Results are cached after the first run.
              </p>
              <p className="text-yellow-200/70 text-xs">Please wait, or check that the backend is running on port 8000.</p>
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
          <button
            onClick={() => setAttempt((a) => a + 1)}
            className="bg-red-700 hover:bg-red-600 text-white text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 w-full h-full overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
        <p className="text-gray-400 text-sm mt-1">
          14-day Prophet forecast for top critical zones
        </p>
      </div>

      {forecasts.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center space-y-3">
          <p className="text-gray-300 font-medium">Forecasts not yet available</p>
          <p className="text-gray-500 text-sm">
            The backend computes Prophet models on first startup. This takes ~60–90 seconds and is then cached.
            If you just restarted the backend, wait a moment and retry.
          </p>
          <button
            onClick={() => setAttempt((a) => a + 1)}
            className="bg-gray-800 hover:bg-gray-700 text-white text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm w-full md:w-auto font-medium"
            >
              {forecasts.map((f) => (
                <option key={f.h3_cell} value={f.h3_cell}>
                  {f.zone_name ? `${f.zone_name}` : f.h3_cell}
                </option>
              ))}
            </select>
            {selected && (
              <span className="text-xs text-gray-500 font-mono">{selected}</span>
            )}
          </div>

          {current && (
            <ForecastChart
              title={current.zone_name ? `${current.zone_name}` : `Zone ${selected}`}
              historical={current.historical as { ds: string; y: number }[]}
              forecast={current.forecast as { ds: string; yhat: number; yhat_lower: number; yhat_upper: number }[]}
            />
          )}

          {topRiskDays.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h3 className="text-white font-semibold mb-3">Top 5 Predicted High-Risk Days</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 text-left">
                    <th className="pb-2">Date</th>
                    <th className="pb-2">Predicted Violations</th>
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
                {current?.zone_name ?? selected} expected to peak on high-risk days — recommend pre-emptive deployment.
              </p>
            </div>
          )}
        </>
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
