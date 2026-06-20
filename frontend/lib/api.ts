const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SummaryStats {
  total_violations: number;
  total_approved: number;
  unique_junctions: number;
  critical_zones_count: number;
  peak_hour_citywide: number | null;
  most_active_station: string | null;
  date_range: { start: string | null; end: string | null };
}

export interface H3Feature {
  type: string;
  geometry: { type: string; coordinates: number[][][] };
  properties: {
    h3_cell: string;
    violation_count: number;
    weighted_count: number;
    cis: number;
    classification: string;
    dominant_vehicle_type?: string;
    dominant_violation_type?: string;
    peak_hour?: number;
    is_junction_cell?: boolean;
    monthly_counts?: Record<string, number>;
    unique_vehicles?: number;
    centroid_lat?: number;
    centroid_lon?: number;
  };
}

export interface EnforcementItem {
  rank: number;
  zone_name: string;
  cis: number;
  classification: string;
  total_violations: number;
  recommended_officers: number;
  recommended_shift: string;
  dominant_violation?: string;
  dominant_vehicle?: string;
  trend: string;
  centroid_lat: number;
  centroid_lon: number;
  police_station?: string;
  h3_cell?: string;
}

export interface AnomalyRecord {
  date: string;
  total_violations: number;
  z_score: number;
  affected_zones: string[];
  likely_cause: string;
}

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const getHealth = () => fetchApi<{ status: string; records_loaded: number }>("/health");
export const getSummaryStats = () => fetchApi<SummaryStats>("/summary/stats");
export const getH3Grid = (month?: string, minCount = 5) => {
  const params = new URLSearchParams({ min_count: String(minCount) });
  if (month) params.set("month", month);
  return fetchApi<{ features: H3Feature[] }>(`/h3-grid?${params}`);
};
export const getHotspots = (limit = 20, month?: string) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (month) params.set("month", month);
  return fetchApi<{ features: unknown[] }>(`/hotspots?${params}`);
};
export const getHeatmapData = (month?: string) => {
  const params = month ? `?month=${month}` : "";
  return fetchApi<{ points: { lat: number; lon: number; weight: number }[] }>(`/heatmap-data${params}`);
};
export const getEnforcementPlan = (date?: string, policeStation?: string) => {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (policeStation) params.set("police_station", policeStation);
  return fetchApi<{ date: string; total_officers: number; zones_count: number; items: EnforcementItem[] }>(
    `/enforcement-plan?${params}`
  );
};
export const getAnomalies = () => fetchApi<{ anomalies: AnomalyRecord[] }>("/anomalies");
export const getSummaryByHour = () => fetchApi<{ hour: number; count: number }[]>("/summary/by-hour");
export const getSummaryByDow = () => fetchApi<{ day_of_week: number; day_name: string; count: number }[]>("/summary/by-dow");
export const getSummaryByMonth = () => fetchApi<{ month_year: string; count: number }[]>("/summary/by-month");
export const getSummaryByStation = () => fetchApi<{ police_station: string; violation_count: number; avg_cis: number }[]>("/summary/by-station");
export const getSummaryByVehicle = () => fetchApi<{ vehicle_type: string; violation_count: number }[]>("/summary/by-vehicle");
export const getSummaryByViolationType = () => fetchApi<{ violation_type: string; count: number }[]>("/summary/by-violation-type");
export const getDailyTrend = () => fetchApi<{ violation_date: string; count: number }[]>("/summary/daily");
export const getTopJunctions = () => fetchApi<{ junction_name: string; violation_count: number; lat: number; lon: number }[]>("/summary/junctions");
export const getTopForecasts = () => fetchApi<{ forecasts: { h3_cell: string; forecast: unknown[]; historical: unknown[] }[] }>("/forecast/top");
export const getForecast = (h3Cell: string) => fetchApi<{ h3_cell: string; forecast: unknown[]; historical: unknown[] }>(`/forecast/${h3Cell}`);

export async function postQuery(question: string) {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return res.json();
}

export function cisColor(classification: string): [number, number, number, number] {
  const map: Record<string, [number, number, number, number]> = {
    CRITICAL: [220, 38, 38, 200],
    HIGH: [234, 88, 12, 200],
    MODERATE: [202, 138, 4, 200],
    LOW: [22, 163, 74, 200],
  };
  return map[classification] || map.LOW;
}

export function cisHex(classification: string): string {
  const map: Record<string, string> = {
    CRITICAL: "#DC2626",
    HIGH: "#EA580C",
    MODERATE: "#CA8A04",
    LOW: "#16A34A",
  };
  return map[classification] || map.LOW;
}

export const MONTHS = [
  { value: "", label: "All Months" },
  { value: "2023-11", label: "Nov 2023" },
  { value: "2023-12", label: "Dec 2023" },
  { value: "2024-01", label: "Jan 2024" },
  { value: "2024-02", label: "Feb 2024" },
  { value: "2024-03", label: "Mar 2024" },
  { value: "2024-04", label: "Apr 2024" },
];
