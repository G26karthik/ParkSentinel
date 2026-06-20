"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Area,
  ComposedChart,
} from "recharts";

interface ForecastChartProps {
  historical: { ds: string; y?: number; count?: number }[];
  forecast: { ds: string; yhat: number; yhat_lower: number; yhat_upper: number }[];
  title?: string;
}

export default function ForecastChart({ historical, forecast, title }: ForecastChartProps) {
  const histData = historical.map((h) => ({
    date: h.ds,
    actual: h.y ?? h.count ?? 0,
  }));

  const forecastData = forecast.map((f) => ({
    date: f.ds,
    predicted: Math.max(0, Math.round(f.yhat)),
    lower: Math.max(0, Math.round(f.yhat_lower)),
    upper: Math.max(0, Math.round(f.yhat_upper)),
  }));

  const combined = [
    ...histData.slice(-90).map((h) => ({ ...h, predicted: undefined })),
    ...forecastData,
  ];

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      {title && <h3 className="text-white font-semibold mb-4">{title}</h3>}
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={combined}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "#9ca3af" }}
            tickFormatter={(v) => v.slice(5)}
          />
          <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} />
          <Tooltip
            contentStyle={{ background: "#1f2937", border: "1px solid #374151" }}
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="upper"
            stroke="none"
            fill="#ef444433"
            name="Upper bound"
          />
          <Area
            type="monotone"
            dataKey="lower"
            stroke="none"
            fill="#111827"
            name="Lower bound"
          />
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={false}
            name="Historical"
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="#ef4444"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            name="Forecast"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
