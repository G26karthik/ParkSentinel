"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, TextLayer, PathLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { EnforcementItem, cisColor, MAP_STYLE } from "@/lib/api";

const BENGALURU = { longitude: 77.5946, latitude: 12.9716, zoom: 10, pitch: 0, bearing: 0 };

interface Props {
  items: EnforcementItem[];
  showRoute?: boolean;
  naiveRouteCoords?: [number, number][];
}

export default function EnforcementMiniMap({ items, showRoute = false, naiveRouteCoords }: Props) {
  const [routeMode, setRouteMode] = useState<"optimized" | "naive">("optimized");
  const [animT, setAnimT] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const ANIM_DURATION = 4000;

  useEffect(() => {
    if (!showRoute) return;
    const tick = (ts: number) => {
      if (startRef.current === null) startRef.current = ts;
      const elapsed = ts - startRef.current;
      setAnimT((elapsed % ANIM_DURATION) / ANIM_DURATION);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      startRef.current = null;
    };
  }, [showRoute]);

  const initialViewState = useMemo(() => {
    const pts = items.filter((i) => i.centroid_lat && i.centroid_lon);
    if (pts.length === 0) return BENGALURU;
    const lat = pts.reduce((s, p) => s + p.centroid_lat, 0) / pts.length;
    const lon = pts.reduce((s, p) => s + p.centroid_lon, 0) / pts.length;
    return { longitude: lon, latitude: lat, zoom: 10.5, pitch: 0, bearing: 0 };
  }, [items]);

  function interpolatePath(path: [number, number][], t: number): [number, number] {
    if (path.length === 0) return [77.5946, 12.9716];
    if (path.length === 1) return path[0];
    const total = path.length - 1;
    const pos = t * total;
    const idx = Math.floor(pos);
    const frac = pos - idx;
    const a = path[Math.min(idx, total)];
    const b = path[Math.min(idx + 1, total)];
    return [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac];
  }

  const optimizedPath = useMemo(
    () =>
      [...items]
        .filter((i) => i.centroid_lon && i.centroid_lat)
        .sort((a, b) => a.rank - b.rank)
        .map((p) => [p.centroid_lon, p.centroid_lat] as [number, number]),
    [items]
  );

  const naivePath: [number, number][] = useMemo(
    () => (naiveRouteCoords ?? []) as [number, number][],
    [naiveRouteCoords]
  );

  const activePath = routeMode === "optimized" ? optimizedPath : naivePath;
  const vehiclePos = interpolatePath(activePath, animT);
  const routeColor: [number, number, number, number] =
    routeMode === "optimized" ? [34, 197, 94, 230] : [234, 179, 8, 230];

  const layers = useMemo(() => {
    const list = [
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
    ];

    if (showRoute && optimizedPath.length > 1) {
      // Grey ghost of naive path when in optimized mode
      if (naivePath.length > 1 && routeMode === "optimized") {
        list.push(
          new PathLayer({
            id: "naive-ghost",
            data: [{ path: naivePath }],
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: [120, 120, 140, 110],
            getWidth: 3,
            widthMinPixels: 2,
            rounded: true,
            pickable: false,
          }) as ReturnType<typeof PathLayer>
        );
      }

      // Active route
      list.push(
        new PathLayer({
          id: "active-route",
          data: [{ path: activePath }],
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: routeColor,
          getWidth: 5,
          widthMinPixels: 3,
          rounded: true,
          pickable: false,
        }) as ReturnType<typeof PathLayer>
      );

      // Animated vehicle marker
      list.push(
        new ScatterplotLayer({
          id: "vehicle-marker",
          data: [{ position: vehiclePos }],
          getPosition: (d: { position: [number, number] }) => d.position,
          getRadius: 220,
          radiusMinPixels: 10,
          radiusMaxPixels: 16,
          getFillColor: [255, 255, 255, 255],
          getLineColor: routeColor,
          stroked: true,
          lineWidthMinPixels: 2.5,
          pickable: false,
        })
      );
    }

    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, showRoute, optimizedPath, naivePath, activePath, vehiclePos, routeMode]);

  return (
    <div className="relative h-72 w-full rounded-xl overflow-hidden border border-gray-800">
      <DeckGL initialViewState={initialViewState} controller={true} layers={layers} style={{ position: "absolute", inset: 0 }}>
        <Map mapStyle={MAP_STYLE} />
      </DeckGL>

      {showRoute && naivePath.length > 1 && (
        <div className="absolute top-2 left-2 flex gap-1.5 z-10">
          <button
            onClick={() => setRouteMode("optimized")}
            className={`text-[10px] px-2 py-1 rounded font-semibold transition-colors ${
              routeMode === "optimized"
                ? "bg-green-600 text-white shadow"
                : "bg-gray-800/90 text-gray-400 hover:text-white"
            }`}
          >
            Smart Route (AI)
          </button>
          <button
            onClick={() => setRouteMode("naive")}
            className={`text-[10px] px-2 py-1 rounded font-semibold transition-colors ${
              routeMode === "naive"
                ? "bg-yellow-600 text-white shadow"
                : "bg-gray-800/90 text-gray-400 hover:text-white"
            }`}
          >
            Standard Order
          </button>
        </div>
      )}

      <div className="absolute bottom-2 left-2 bg-gray-950/80 rounded-md px-2 py-1 text-[10px] text-gray-300 pointer-events-none">
        {showRoute
          ? routeMode === "optimized"
            ? "Green = VRP route · grey ghost = naive · dot = patrol vehicle"
            : "Amber = naive CIS-order route"
          : "Numbered by enforcement rank · color = CIS band"}
      </div>
    </div>
  );
}
