import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { maplibregl, mapStyle, colourMap } from "../location/mapRuntime";
import type { Map as LibreMap, Marker } from "maplibre-gl";
import type { PublicSummary } from "./api";
import { boundsQuery, type Bounds } from "./mapSearch";
import { formatEUR } from "../listings/form";
import { PublicPhotos } from "./PublicPhotos";

export type ResultsMapProps = {
  items: PublicSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onBounds: (bounds: Bounds) => void;
  bounds: Bounds | null;
  query: string;
  onList: () => void;
};
export default function ResultsMap({
  items,
  selected,
  onSelect,
  onBounds,
  bounds,
  query,
  onList,
}: ResultsMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const callbacks = useRef({ onSelect, onBounds });
  const [state, setState] = useState("loading");
  const [attempt, setAttempt] = useState(0);
  const [overlap, setOverlap] = useState<string[]>([]);
  const fitted = useRef("");
  const emitted = useRef("");
  useEffect(() => {
    callbacks.current = { onSelect, onBounds };
  }, [onSelect, onBounds]);
  useEffect(() => {
    if (!container.current) return;
    let map: LibreMap | null = null;
    let timer: ReturnType<typeof setTimeout>;
    try {
      map = new maplibregl.Map({
        container: container.current,
        style: mapStyle,
        center: [0, 20],
        zoom: 1,
        maxZoom: 12,
        scrollZoom: false,
        keyboard: true,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        attributionControl: { compact: false },
      });
      mapRef.current = map;
      map
        .getCanvas()
        .setAttribute(
          "aria-label",
          "Approximate stay map. Arrow keys pan; plus and minus zoom.",
        );
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      map.on("style.load", () => {
        if (map) colourMap(map);
      });
      function emitBounds() {
        if (!map) return;
        const b = map.getBounds();
        const span = b.getEast() - b.getWest();
        const wrap = (v: number) => ((((v + 180) % 360) + 360) % 360) - 180;
        const area = {
          west: span >= 360 ? -180 : wrap(b.getWest()),
          east: span >= 360 ? 180 : wrap(b.getEast()),
          south: Math.max(-90, b.getSouth()),
          north: Math.min(90, b.getNorth()),
        };
        emitted.current = JSON.stringify(boundsQuery(area));
        callbacks.current.onBounds(area);
      }
      map.on("load", () => {
        clearTimeout(timer);
        setState("ready");
        emitBounds();
      });
      map.on("error", () => {
        clearTimeout(timer);
        setState("failed");
      });
      map.on("webglcontextlost", () => setState("failed"));
      map.on("moveend", emitBounds);
      timer = setTimeout(() => setState("failed"), 18000);
    } catch {
      timer = setTimeout(() => setState("failed"), 0);
    }
    return () => {
      clearTimeout(timer);
      markers.current.forEach((marker) => marker.remove());
      markers.current = [];
      map?.remove();
      mapRef.current = null;
      fitted.current = "";
    };
  }, [attempt]);
  // Bounds from URL are applied once per external history/search navigation.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const key = bounds
      ? JSON.stringify(bounds)
      : items.map((item) => item.id).join(",");
    if (!key || fitted.current === key) return;
    fitted.current = key;
    if (bounds) {
      if (JSON.stringify(boundsQuery(bounds)) === emitted.current) return;
      const east = bounds.east < bounds.west ? bounds.east + 360 : bounds.east;
      map.fitBounds(
        [
          [bounds.west, bounds.south],
          [east, bounds.north],
        ],
        { padding: 0, duration: 0, maxZoom: 12 },
      );
    } else if (items.some((item) => item.location)) {
      const b = new maplibregl.LngLatBounds();
      items.forEach((item) => {
        if (item.location)
          b.extend([item.location.longitude, item.location.latitude]);
      });
      map.fitBounds(b, { padding: 70, maxZoom: 11, duration: 0 });
    }
  }, [items, bounds, attempt]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const focusedLabel = markers.current
      .map((marker) => marker.getElement())
      .find((element) => element === document.activeElement)
      ?.getAttribute("aria-label");
    markers.current.forEach((marker) => marker.remove());
    markers.current = [];
    const groups = new Map<string, PublicSummary[]>();
    items.forEach((item) => {
      if (!item.location) return;
      const key = `${item.location.latitude}:${item.location.longitude}`;
      groups.set(key, [...(groups.get(key) ?? []), item]);
    });
    for (const group of groups.values()) {
      const active = group.find((item) => item.id === selected) ?? group[0];
      const button = document.createElement("button");
      button.type = "button";
      button.className = `map-price-pin${group.some((item) => item.id === selected) ? " selected" : ""}`;
      button.textContent = `${formatEUR(active.nightly_minor)}${group.length > 1 ? ` +${group.length - 1}` : ""}`;
      button.setAttribute(
        "aria-label",
        `${group.length > 1 ? `${group.length} stays · ` : ""}${active.title} · ${formatEUR(active.nightly_minor)} per night`,
      );
      button.setAttribute(
        "aria-pressed",
        String(group.some((item) => item.id === selected)),
      );
      button.addEventListener("click", () => {
        setOverlap(group.length > 1 ? group.map((item) => item.id) : []);
        callbacks.current.onSelect(active.id);
      });
      markers.current.push(
        new maplibregl.Marker({ element: button })
          .setLngLat([active.location!.longitude, active.location!.latitude])
          .addTo(map),
      );
      if (
        focusedLabel &&
        (button.getAttribute("aria-label") === focusedLabel ||
          group.some((item) => item.id === selected))
      )
        button.focus({ preventScroll: true });
    }
  }, [items, selected, attempt]);
  const current = items.find((item) => item.id === selected);
  const overlapItems = items.filter((item) => overlap.includes(item.id));
  return (
    <section className="results-map-panel" aria-label="Stay price map">
      <div className="results-map-canvas" ref={container} />
      <span className="map-price-label">
        Approximate locations · prices per night
      </span>
      {state === "loading" && (
        <p className="results-map-status" role="status">
          Loading map…
        </p>
      )}
      {state === "failed" && (
        <div className="results-map-failure" role="status">
          <strong>Map unavailable</strong>
          <p>The stay list and filters still work.</p>
          <button
            className="button secondary"
            onClick={() => {
              setState("loading");
              setAttempt((value) => value + 1);
            }}
          >
            Retry map
          </button>
          <button className="button secondary" onClick={onList}>
            Browse list
          </button>
        </div>
      )}
      {overlapItems.length > 1 && (
        <fieldset className="map-overlap-picker">
          <legend>Stays sharing this approximate point</legend>
          {items
            .filter((item) => overlap.includes(item.id))
            .map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === selected}
                onClick={() => onSelect(item.id)}
              >
                {item.title} · {formatEUR(item.nightly_minor)}/night
              </button>
            ))}
        </fieldset>
      )}
      {current && (
        <article className="map-stay-preview">
          <PublicPhotos
            key={current.id}
            listingId={current.id}
            photos={current.photos}
            title={current.title}
          />
          <div>
            <Link to={`/stays/${current.id}?${query}`}>
              <strong>{current.title}</strong>
            </Link>
            <p>{current.destination}</p>
            <p>
              {formatEUR(current.nightly_minor)} / night
              {current.stay_price
                ? ` · ${formatEUR(current.stay_price.total_minor)} stay total`
                : ""}
            </p>
            <button
              type="button"
              className="map-preview-close"
              aria-label="Close stay preview"
              onClick={() => onSelect("")}
            >
              ×
            </button>
          </div>
        </article>
      )}
    </section>
  );
}
