"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ForecastChart from "@/components/ForecastChart";
import { getTopForecasts, getForecast } from "@/lib/api";

function ForecastContent() {
  const searchParams = useSearchParams();
  const cellParam = searchParams.get("cell");
  const [forecasts, setForecasts] = useState<
    { h3_cell: string; forecast: unknown[]; historical: unknown[] }[]
  >([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await getTopForecasts();
        setForecasts(data.forecasts);
        if (cellParam && data.forecasts.some((f) => f.h3_cell === cellParam)) {
          setSelected(cellParam);
        } else if (data.forecasts.length > 0) {
          setSelected(data.forecasts[0].h3_cell);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [cellParam]);

  const current = forecasts.find((f) => f.h3_cell === selected);

  const topRiskDays = current
    ? (current.forecast as { ds: string; yhat: number }[])
        .map((f) => ({ date: f.ds, predicted: Math.round(f.yhat) }))
        .sort((a, b) => b.predicted - a.predicted)
        .slice(0, 5)
    : [];

  if (loading) {
    return <div className="p-8 text-gray-400">Loading forecasts...</div>;
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Violation Forecast</h1>
        <p className="text-gray-400 text-sm mt-1">
          14-day Prophet forecast for top critical zones
        </p>
      </div>

      {forecasts.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-400">
          <p>Forecasts are being computed on first startup.</p>
          <p className="text-sm mt-2">Restart the backend after Prophet models finish training.</p>
        </div>
      ) : (
        <>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm w-full md:w-auto"
          >
            {forecasts.map((f) => (
              <option key={f.h3_cell} value={f.h3_cell}>
                {f.h3_cell}
              </option>
            ))}
          </select>

          {current && (
            <ForecastChart
              title={`Zone ${selected}`}
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
                Zone {selected} expected to peak on high-risk days — recommend pre-emptive deployment.
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
