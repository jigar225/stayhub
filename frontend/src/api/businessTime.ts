import { useEffect, useSyncExternalStore } from "react";
import { publicRequest } from "./client";
type ClockState = {
  anchor: number | null;
  elapsedAt: number;
  error: string;
  version: number;
};
let state: ClockState = { anchor: null, elapsedAt: 0, error: "", version: 0 };
const listeners = new Set<() => void>();
let flight: Promise<void> | null = null;
const publish = (next: ClockState) => {
  state = next;
  listeners.forEach((listener) => listener());
};
export function businessNow(): Date | null {
  return state.anchor === null
    ? null
    : new Date(state.anchor + Math.max(0, performance.now() - state.elapsedAt));
}
export function refreshBusinessTime() {
  if (flight) return flight;
  flight = publicRequest<{ business_now: string; real_now: string }>(
    "/business-time",
  )
    .then((result) => {
      const anchor = Date.parse(result.business_now);
      if (!Number.isFinite(anchor))
        throw new Error("Invalid business time response.");
      publish({
        anchor,
        elapsedAt: performance.now(),
        error: "",
        version: state.version + 1,
      });
    })
    .catch(() => {
      publish({
        ...state,
        error:
          "Could not refresh StayHub’s business time. Date choices are advisory; the server will validate your dates.",
        version: state.version + 1,
      });
    })
    .finally(() => {
      flight = null;
    });
  return flight;
}
export function useBusinessTime() {
  const snapshot = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => state,
  );
  useEffect(() => {
    void refreshBusinessTime();
    const timer = window.setInterval(
      () => publish({ ...state, version: state.version + 1 }),
      1000,
    );
    const focus = () => void refreshBusinessTime();
    window.addEventListener("focus", focus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, []);
  return {
    now: businessNow(),
    error: snapshot.error,
    refresh: refreshBusinessTime,
  };
}
