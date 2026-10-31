import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as LibreMap, Marker } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Point } from "./api";
import "./location.css";

maplibregl.setWorkerUrl(workerUrl);
const style =
  import.meta.env.VITE_MAP_STYLE_URL ||
  "https://tiles.openfreemap.org/styles/positron";

export default function LocationMap({
  point,
  approximate = false,
  onChange,
  disabled = false,
}: {
  point: Point | null;
  approximate?: boolean;
  onChange?: (point: Point) => void;
  disabled?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const changeRef = useRef(onChange);
  const disabledRef = useRef(disabled);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    changeRef.current = onChange;
    disabledRef.current = disabled;
  }, [onChange, disabled]);
  useEffect(() => {
    if (!container.current) return;
    let map: LibreMap | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      map = new maplibregl.Map({
        container: container.current,
        style,
        center: point ? [point.longitude, point.latitude] : [0, 20],
        zoom: point ? (approximate ? 11 : 14) : 1,
        maxZoom: approximate ? 12 : 19,
        scrollZoom: false,
        keyboard: false,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        attributionControl: { compact: false },
      });
      mapRef.current = map;
      map.on("style.load", () => {
        if (!map || import.meta.env.VITE_MAP_STYLE_URL) return;
        // Keep the light street/label styling while adding StayHub's soft colours.
        for (const [id, color] of [
          ["park", "#dcebd7"],
          ["landcover_wood", "#dcebd7"],
          ["water", "#cfe3eb"],
        ]) {
          if (map.getLayer(id)) map.setPaintProperty(id, "fill-color", color);
        }
      });
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      map.on("click", (event) => {
        if (!disabledRef.current)
          changeRef.current?.({
            latitude: event.lngLat.lat,
            longitude: event.lngLat.wrap().lng,
          });
      });
      map.on("load", () => {
        clearTimeout(timer);
        setState("ready");
      });
      map.on("error", () => {
        clearTimeout(timer);
        setState("failed");
      });
      map.on("webglcontextlost", () => setState("failed"));
      timer = setTimeout(() => setState("failed"), 18000);
    } catch {
      timer = setTimeout(() => setState("failed"), 0);
    }
    return () => {
      clearTimeout(timer);
      markerRef.current?.remove();
      markerRef.current = null;
      map?.remove();
      mapRef.current = null;
    };
    // Point changes update the same map below, rather than recreating WebGL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approximate, attempt]);
  const latitude = point?.latitude;
  const longitude = point?.longitude;
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (latitude === undefined || longitude === undefined) return;
    map.jumpTo({
      center: [longitude, latitude],
      zoom: approximate ? 11 : Math.max(14, map.getZoom()),
    });
    if (approximate) {
      const drawArea = () => {
        if (!map.isStyleLoaded()) return;
        if (map.getLayer("location-area-fill"))
          map.removeLayer("location-area-fill");
        if (map.getLayer("location-area-outline"))
          map.removeLayer("location-area-outline");
        if (map.getSource("location-area")) map.removeSource("location-area");
        const ring = Array.from({ length: 65 }, (_, index) => {
          const angle = (index * Math.PI) / 32;
          return [
            longitude +
              (800 * Math.cos(angle)) /
                (111320 * Math.max(0.01, Math.cos((latitude * Math.PI) / 180))),
            Math.max(
              -90,
              Math.min(90, latitude + (800 * Math.sin(angle)) / 111320),
            ),
          ];
        });
        map.addSource("location-area", {
          type: "geojson",
          data: {
            type: "Feature",
            properties: {},
            geometry: { type: "Polygon", coordinates: [ring] },
          },
        });
        map.addLayer({
          id: "location-area-fill",
          type: "fill",
          source: "location-area",
          paint: { "fill-color": "#0b6b5d", "fill-opacity": 0.15 },
        });
        map.addLayer({
          id: "location-area-outline",
          type: "line",
          source: "location-area",
          paint: { "line-color": "#0b6b5d", "line-width": 2 },
        });
      };
      if (map.isStyleLoaded()) drawArea();
      else map.once("load", drawArea);
      return () => {
        map.off("load", drawArea);
      };
    }
    const element = document.createElement("div");
    element.className = "location-exact-marker";
    element.setAttribute("aria-label", "Selected location");
    const marker = new maplibregl.Marker({ element, draggable: !disabled })
      .setLngLat([longitude, latitude])
      .addTo(map);
    marker.on("dragend", () => {
      const position = marker.getLngLat().wrap();
      if (!disabledRef.current)
        changeRef.current?.({
          latitude: position.lat,
          longitude: position.lng,
        });
    });
    markerRef.current = marker;
  }, [latitude, longitude, approximate, disabled, attempt]);
  return (
    <div className="location-map-shell">
      <div
        className="location-map-canvas"
        ref={container}
        aria-label={
          approximate ? "Map of approximate location" : "Location pin map"
        }
      />
      {state === "loading" && (
        <p className="location-map-notice" aria-live="polite">
          Loading map…
        </p>
      )}
      {state === "failed" && (
        <div className="location-map-fallback" aria-live="polite">
          <strong>Map unavailable</strong>
          <p>
            {approximate
              ? "You can still view this stay and reserve. Try loading the map again."
              : "Enter and confirm coordinates below. Your address and other edits are kept."}
          </p>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setState("loading");
              setAttempt((value) => value + 1);
            }}
          >
            Retry map
          </button>
        </div>
      )}
    </div>
  );
}
