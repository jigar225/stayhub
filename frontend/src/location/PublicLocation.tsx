import { useEffect, useState } from "react";
import { locationApi, type ApproximateLocation } from "./api";
import "./location.css";
import { MapPanel } from "./MapPanel";
export function PublicLocation({ listingId }: { listingId: string }) {
  const [result, setResult] = useState<{
    listingId: string;
    point: ApproximateLocation | null;
  } | null>(null);
  const [error, setError] = useState<{
    listingId: string;
    message: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void locationApi
      .publicLocation(listingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setResult({ listingId, point: data.location });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError({
            listingId,
            message:
              "The location map could not be loaded. The rest of this stay is still available.",
          });
      });
    return () => controller.abort();
  }, [listingId, attempt]);
  if (error?.listingId === listingId)
    return (
      <div className="location-inline-fallback" role="status">
        <p>{error.message}</p>
        <button
          type="button"
          className="button secondary"
          onClick={() => {
            setError(null);
            setAttempt((value) => value + 1);
          }}
        >
          Retry location
        </button>
      </div>
    );
  if (!result || result.listingId !== listingId)
    return <p role="status">Loading location…</p>;
  if (!result.point) return null;
  return (
    <div className="location-public">
      <p className="location-public-label">
        <strong>Approximate location</strong>
      </p>
      <MapPanel point={result.point} approximate />
      <p className="field-help">
        This map shows an approximate area, not the exact address.
      </p>
    </div>
  );
}
