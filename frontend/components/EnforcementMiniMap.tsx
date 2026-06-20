"use client";

import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import { EnforcementItem, cisColor } from "@/lib/api";

const BENGALURU = { longitude: 77.5946, latitude: 12.9716, zoom: 10, pitch: 0, bearing: 0 };

export default function EnforcementMiniMap({ items }: { items: EnforcementItem[] }) {
  const initialViewState = useMemo(() => {
    const pts = items.filter((i) => i.centroid_lat && i.centroid_lon);
    if (pts.length === 0) return BENGALURU;
    const lat = pts.reduce((s, p) => s + p.centroid_lat, 0) / pts.length;
    const lon = pts.reduce((s, p) => s + p.centroid_lon, 0) / pts.length;
    return { longitude: lon, latitude: lat, zoom: 10.5, pitch: 0, bearing: 0 };
  }, [items]);

  const layers = useMemo(
    () => [
      new ScatterplotLayer({
        id: "enf-zones",
        data: items,
        getPosition: (d: EnforcementItem) => [d.centroid_lon, d.centroid_lat],
        getRadius: (d: EnforcementItem) => 150 + d.cis * 8,
        radiusMinPixels: 8,
        radiusMaxPixels: 28,
        stroked: true,
        getFillColor: (d: EnforcementItem) => cisColor(d.classification),
        getLineColor: [255, 255, 255, 220],
        lineWidthMinPixels: 1.5,
        pickable: true,
      }),
      new TextLayer({
        id: "enf-rank",
        data: items,
        getPosition: (d: EnforcementItem) => [d.centroid_lon, d.centroid_lat],
        getText: (d: EnforcementItem) => String(d.rank),
        getSize: 11,
        sizeUnits: "pixels",
        getColor: [255, 255, 255, 255],
        fontWeight: 700,
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
        billboard: true,
      }),
    ],
    [items]
  );

  return (
    <div className="relative h-64 w-full rounded-xl overflow-hidden border border-gray-800">
      <DeckGL initialViewState={initialViewState} controller={true} layers={layers} style={{ position: "absolute", inset: 0 }}>
        <Map mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json" style={{ width: "100%", height: "100%" }} />
      </DeckGL>
      <div className="absolute bottom-2 left-2 bg-gray-950/80 rounded-md px-2 py-1 text-[10px] text-gray-300 pointer-events-none">
        Numbered by enforcement rank · color = CIS band
      </div>
    </div>
  );
}
