"use client";

import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";

// Junction names arrive like "BTP051 - Safina Plaza Junction"; drop the code prefix for a clean label.
function cleanJunctionName(name: string): string {
  return (name || "").replace(/^[A-Z]+\d+\s*-\s*/i, "").replace(/\s*Junction$/i, "").trim() || name;
}
import Map from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { H3Feature, cisColor, MAP_STYLE } from "@/lib/api";

const INITIAL_VIEW = {
  longitude: 77.5946,
  latitude: 12.9716,
  zoom: 11,
  pitch: 45,
  bearing: 0,
};

interface MapViewProps {
  h3Data: H3Feature[];
  heatmapPoints: { lat: number; lon: number; weight: number }[];
  junctions: { junction_name: string; violation_count: number; lat: number; lon: number }[];
  layerMode: "hex" | "heatmap" | "both";
  onSelect: (feature: H3Feature) => void;
}

export default function MapView({
  h3Data,
  heatmapPoints,
  junctions,
  layerMode,
  onSelect,
}: MapViewProps) {
  const layers = useMemo(() => {
    const result = [];

    if (layerMode === "hex" || layerMode === "both") {
      result.push(
        new GeoJsonLayer({
          id: "h3-hexagons",
          data: { type: "FeatureCollection", features: h3Data },
          pickable: true,
          stroked: true,
          filled: true,
          extruded: true,
          wireframe: false,
          getElevation: (f: { properties: { violation_count: number } }) =>
            Math.min(f.properties.violation_count * 5, 3000),
          elevationScale: 1,
          getFillColor: (f: { properties: { classification: string } }) =>
            cisColor(f.properties.classification),
          getLineColor: [255, 255, 255, 80],
          getLineWidth: 1,
          opacity: 0.75,
          onClick: (info: { object?: H3Feature }) => {
            if (info.object) onSelect(info.object);
          },
        })
      );
    }

    if (layerMode === "heatmap" || layerMode === "both") {
      result.push(
        new HeatmapLayer({
          id: "heatmap",
          data: heatmapPoints,
          getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
          getWeight: (d: { weight: number }) => d.weight,
          radiusPixels: 40,
          intensity: 1,
          threshold: 0.05,
          opacity: layerMode === "both" ? 0.4 : 0.8,
        })
      );
    }

    if (junctions.length > 0) {
      result.push(
        new ScatterplotLayer({
          id: "junctions",
          data: junctions,
          getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
          getRadius: (d: { violation_count: number }) => Math.sqrt(d.violation_count) * 80,
          radiusMinPixels: 6,
          radiusMaxPixels: 30,
          getFillColor: [59, 130, 246, 200],
          getLineColor: [255, 255, 255, 255],
          lineWidthMinPixels: 1,
          pickable: true,
        })
      );
      result.push(
        new TextLayer({
          id: "junction-labels",
          data: junctions,
          getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
          getText: (d: { junction_name: string }) => cleanJunctionName(d.junction_name),
          getSize: 12,
          sizeUnits: "pixels",
          getColor: [226, 232, 240, 255],
          getPixelOffset: [0, -16],
          getTextAnchor: "middle",
          getAlignmentBaseline: "bottom",
          fontWeight: 600,
          outlineWidth: 2,
          outlineColor: [2, 6, 23, 255],
          fontSettings: { sdf: true },
          billboard: true,
          background: false,
          pickable: false,
        })
      );
    }

    return result;
  }, [h3Data, heatmapPoints, junctions, layerMode, onSelect]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <DeckGL
        initialViewState={INITIAL_VIEW}
        controller={true}
        layers={layers}
        style={{ width: "100%", height: "100%" }}
        getCursor={({ isHovering }: { isHovering: boolean }) =>
          isHovering ? "pointer" : "grab"
        }
      >
        <Map
          mapStyle={MAP_STYLE}
        />
      </DeckGL>
      {/* Click hint */}
      <div className="absolute bottom-3 right-3 bg-gray-950/80 border border-gray-800 rounded-lg px-3 py-1.5 text-[10px] text-gray-400 pointer-events-none select-none backdrop-blur-sm">
        {layerMode === "heatmap"
          ? "🔥 Heatmap mode — switch to Hex or Both to select a zone"
          : "🖱️ Click a coloured zone for details · Scroll to zoom"}
      </div>
    </div>
  );
}
