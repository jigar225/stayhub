import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
maplibregl.setWorkerUrl(workerUrl);
export { maplibregl };
export const mapStyle =
  import.meta.env.VITE_MAP_STYLE_URL ||
  "https://tiles.openfreemap.org/styles/positron";
export function colourMap(map: maplibregl.Map) {
  if (import.meta.env.VITE_MAP_STYLE_URL) return;
  for (const [id, color] of [
    ["park", "#dcebd7"],
    ["landcover_wood", "#dcebd7"],
    ["water", "#cfe3eb"],
  ]) {
    if (map.getLayer(id)) map.setPaintProperty(id, "fill-color", color);
  }
}
