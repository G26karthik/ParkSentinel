"use client";

import { MONTHS } from "@/lib/api";

interface TimeFilterProps {
  month: string;
  onChange: (month: string) => void;
}

export default function TimeFilter({ month, onChange }: TimeFilterProps) {
  return (
    <select
      value={month}
      onChange={(e) => onChange(e.target.value)}
      className="bg-gray-900/90 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
    >
      {MONTHS.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  );
}
