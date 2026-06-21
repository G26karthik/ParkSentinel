"use client";

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Scatter,
  ComposedChart,
} from "recharts";
import {
  getSummaryByHour,
  getSummaryByDow,
  getSummaryByMonth,
  getSummaryByStation,
  getSummaryByVehicle,
  getSummaryByViolationType,
  getDailyTrend,
  getAnomalies,
} from "@/lib/api";

const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899"];

export default function AnalyticsPage() {
  const [hourly, setHourly] = useState<{ hour: number; count: number }[]>([]);
  const [dow, setDow] = useState<{ day_name: string; count: number }[]>([]);
  const [monthly, setMonthly] = useState<{ month_year: string; count: number }[]>([]);
  const [stations, setStations] = useState<{ police_station: string; violation_count: number }[]>([]);
  const [vehicles, setVehicles] = useState<{ vehicle_type: string; violation_count: number }[]>([]);
  const [violations, setViolations] = useState<{ violation_type: string; count: number }[]>([]);
  const [daily, setDaily] = useState<{ violation_date: string; count: number }[]>([]);
  const [anomalyDates, setAnomalyDates] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [h, d, m, s, v, vt, dailyData, anom] = await Promise.all([
          getSummaryByHour(),
          getSummaryByDow(),
          getSummaryByMonth(),
          getSummaryByStation(),
          getSummaryByVehicle(),
          getSummaryByViolationType(),
          getDailyTrend(),
          getAnomalies(),
        ]);
        setHourly(h);
        setDow(d.map((x) => ({ day_name: x.day_name, count: x.count })));
        setMonthly(m);
        setStations(s.slice(0, 15));
        setVehicles(v.slice(0, 10));
        setViolations(vt);
        setDaily(dailyData);
        setAnomalyDates(new Set(anom.anomalies.map((a) => a.date)));
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const dailyWithAnomaly = daily.map((d) => ({
    ...d,
    isAnomaly: anomalyDates.has(d.violation_date),
  }));

  if (loading) {
    return <div className="p-8 text-gray-400">Loading analytics...</div>;
  }

  return (
    <div className="p-6 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <p className="text-gray-400 text-sm mt-1">Bengaluru parking violation patterns Nov 2023 – Apr 2024</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <ChartCard title="Violations by Hour of Day">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={hourly} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="hour" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
              <Bar dataKey="count" fill="#ef4444" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Violations by Day of Week">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={dow} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="day_name" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
              <Bar dataKey="count" fill="#f97316" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Monthly Violation Trend">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={monthly} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="month_year" tick={{ fill: "#9ca3af", fontSize: 11 }} interval={0} />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
              <Line type="monotone" dataKey="count" stroke="#60a5fa" strokeWidth={2} dot />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-gray-500 mt-2 leading-relaxed">
            *Note: February (1,719 approved / 3.1% rate) and March (7,038 approved / 12.7% rate) show artificially low counts due to a data validation backlog in the raw police dataset.
          </p>
        </ChartCard>

        <ChartCard title="Vehicle Type Distribution">
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={vehicles}
                dataKey="violation_count"
                nameKey="vehicle_type"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label={({ name, percent }: { name: string; percent: number }) =>
                  percent >= 0.03 ? `${name} ${(percent * 100).toFixed(0)}%` : ""
                }
                labelLine={false}
              >
                {vehicles.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Top 15 Police Stations">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={stations} layout="vertical" margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="police_station"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                width={90}
              />
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
              <Bar dataKey="violation_count" fill="#8b5cf6" radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Violation Type Distribution">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={violations} layout="vertical" margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="violation_type"
                tick={{ fill: "#9ca3af", fontSize: 9 }}
                width={130}
              />
              <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
              <Bar dataKey="count" fill="#22c55e" radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <ChartCard title="Daily Violations with Anomaly Detection">
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={dailyWithAnomaly} margin={{ top: 10, right: 20, left: 5, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="violation_date"
              tick={{ fill: "#9ca3af", fontSize: 9 }}
              tickFormatter={(v) => v.slice(5)}
              minTickGap={20}
            />
            <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
            <Tooltip contentStyle={{ background: "#1f2937", border: "none" }} />
            <Line type="monotone" dataKey="count" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
            <Scatter
              dataKey="count"
              fill="#ef4444"
              shape="circle"
              data={dailyWithAnomaly.filter((d) => d.isAnomaly)}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <p className="text-xs text-gray-500 mt-2">Red dots indicate anomaly dates (7-day rolling-baseline method)</p>
      </ChartCard>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h3 className="text-white font-semibold mb-3 text-sm">{title}</h3>
      {children}
    </div>
  );
}
