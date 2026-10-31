import { useEffect, useState, type ComponentType } from "react";
import { MapBoundary } from "../location/MapPanel";
import type { ResultsMapProps } from "./ResultsMap";
export function ResultsMapPanel(props: ResultsMapProps) {
  const [loaded, setLoaded] = useState<{
    component: ComponentType<ResultsMapProps>;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void import("./ResultsMap")
      .then((module) => {
        if (active) setLoaded({ component: module.default });
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  function retry() {
    setFailed(false);
    setLoaded(null);
    setAttempt((value) => value + 1);
  }
  if (failed)
    return (
      <div role="status">
        <p>Map unavailable. The list still works.</p>
        <button className="button secondary" onClick={retry}>
          Retry map
        </button>
        <button className="button secondary" onClick={props.onList}>
          Browse list
        </button>
      </div>
    );
  const Loaded = loaded?.component;
  return Loaded ? (
    <MapBoundary key={attempt} retry={retry}>
      <Loaded {...props} />
    </MapBoundary>
  ) : (
    <p role="status">Loading map…</p>
  );
}
