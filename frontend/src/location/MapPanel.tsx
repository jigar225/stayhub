import {
  Component,
  useEffect,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import type { Point } from "./api";

type MapProps = {
  point: Point | null;
  approximate?: boolean;
  onChange?: (point: Point) => void;
  disabled?: boolean;
};
export class MapBoundary extends Component<
  { children: ReactNode; retry: () => void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <MapFailure retry={this.props.retry} />
    ) : (
      this.props.children
    );
  }
}
function MapFailure({ retry }: { retry: () => void }) {
  return (
    <div className="location-inline-fallback" aria-live="polite">
      <strong>Map unavailable</strong>
      <p>You can keep browsing stays. Your other controls remain available.</p>
      <button className="button secondary" type="button" onClick={retry}>
        Retry map
      </button>
    </div>
  );
}
export function MapPanel(props: MapProps) {
  const [loaded, setLoaded] = useState<{
    component: ComponentType<MapProps>;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void import("./LocationMap")
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
  const retry = () => {
    setFailed(false);
    setLoaded(null);
    setAttempt((value) => value + 1);
  };
  if (failed) return <MapFailure retry={retry} />;
  const LoadedMap = loaded?.component;
  if (!LoadedMap) return <p aria-live="polite">Loading map…</p>;
  return (
    <MapBoundary key={attempt} retry={retry}>
      <LoadedMap {...props} />
    </MapBoundary>
  );
}
