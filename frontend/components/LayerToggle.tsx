"use client";

type LayerMode = "hex" | "heatmap" | "both";

interface LayerToggleProps {
  mode: LayerMode;
  onChange: (mode: LayerMode) => void;
}

export default function LayerToggle({ mode, onChange }: LayerToggleProps) {
  const options: { value: LayerMode; label: string }[] = [
    { value: "hex", label: "Hex" },
    { value: "heatmap", label: "Heatmap" },
    { value: "both", label: "Both" },
  ];

  return (
    <div className="flex bg-gray-900/90 border border-gray-700 rounded-lg overflow-hidden">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-2 text-sm transition-colors ${
            mode === opt.value
              ? "bg-red-600 text-white"
              : "text-gray-400 hover:text-white"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
