import { useEffect, useRef, useState } from "react";
import { bookingApi } from "./api";
import type { PublicPhoto } from "../discovery/api";

// A long paginated Trips list must not start an unbounded set of photo calls.
let running = 0;
const queue: (() => void)[] = [];
async function limitedPhotoRequest<T>(operation: () => Promise<T>): Promise<T> {
  if (running >= 2) await new Promise<void>((resolve) => queue.push(resolve));
  else running++;
  try {
    return await operation();
  } finally {
    const next = queue.shift();
    if (next) next();
    else running--;
  }
}
export function TripPhoto({
  reservationId,
  title,
}: {
  reservationId: string;
  title: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(
    () => typeof IntersectionObserver === "undefined",
  );
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    id: string;
    attempt: number;
    photo: PublicPhoto | null;
    error: boolean;
  } | null>(null);
  const automaticRenewal = useRef(false);
  useEffect(() => {
    if (!container.current) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    void limitedPhotoRequest(async () => {
      if (!active) return;
      const data = await bookingApi.photos(reservationId);
      if (active)
        setResult({
          id: reservationId,
          attempt,
          photo: data.items[0] ?? null,
          error: false,
        });
    }).catch(() => {
      if (active)
        setResult({ id: reservationId, attempt, photo: null, error: true });
    });
    return () => {
      active = false;
    };
  }, [visible, reservationId, attempt]);
  const current =
    result?.id === reservationId && result.attempt === attempt ? result : null;
  const failed = () => {
    if (!automaticRenewal.current) {
      automaticRenewal.current = true;
      setAttempt((value) => value + 1);
    } else {
      setResult({ id: reservationId, attempt, photo: null, error: true });
    }
  };
  return (
    <div
      className="trip-card-photo"
      ref={container}
      aria-busy={visible && !current}
    >
      {!visible || !current ? (
        <p role="status">Loading stay photo…</p>
      ) : current.error ? (
        <div className="trip-photo-fallback">
          <p>Stay photo unavailable.</p>
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              automaticRenewal.current = false;
              setAttempt((value) => value + 1);
            }}
          >
            Retry stay photo
          </button>
        </div>
      ) : current.photo ? (
        <img
          src={current.photo.url}
          alt={title}
          loading="lazy"
          onError={failed}
        />
      ) : (
        <p>No stay photo available.</p>
      )}
    </div>
  );
}
