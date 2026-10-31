import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { authenticated } from "../api/client";
import { bookingError } from "../booking/api";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { ReviewContent } from "./ReviewForm";
import type { Review } from "./api";

type Page = {
  items: (Review & { listing_id: string; listing_title: string })[];
  average: number | null;
  count: number;
  next_cursor: string | null;
};
export function HostReviews() {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    void authenticated<Page>("/host/reviews", { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setPage(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(bookingError(e));
      });
    return () => controller.abort();
  }, [attempt]);
  async function more() {
    const controller = active.current;
    if (!page?.next_cursor || busy || !controller) return;
    setBusy(true);
    setError("");
    try {
      const next = await authenticated<Page>(
        `/host/reviews?cursor=${encodeURIComponent(page.next_cursor)}`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted)
        setPage({ ...next, items: [...page.items, ...next.items] });
    } catch (e) {
      if (!controller.signal.aborted) setError(bookingError(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <main className="host-content host-reviews-page">
      <div className="page-heading">
        <h1>Guest reviews</h1>
        <p>Feedback from stays across your properties.</p>
      </div>
      <p className="muted">
        Reviews appear after both parties submit or the 14-day review window
        closes.
      </p>
      {error && (
        <ErrorState
          message={error}
          retry={() => {
            setBusy(false);
            setError("");
            setAttempt((n) => n + 1);
          }}
        />
      )}
      {!page && !error && <p role="status">Loading guest reviews…</p>}
      {page && (
        <>
          {page.count > 0 && (
            <section
              className="host-review-summary"
              aria-label="Overall guest rating"
            >
              <div>
                <span className="host-review-score">
                  {page.average?.toFixed(2) ?? "—"}
                </span>
                <span> / 5 overall</span>
              </div>
              <p>
                {page.count} published {page.count === 1 ? "review" : "reviews"}{" "}
                · All your properties
              </p>
            </section>
          )}
          {!page.items.length ? (
            <EmptyState title="Your first review is still to come">
              Published feedback from completed stays will appear here.
            </EmptyState>
          ) : (
            <div className="host-review-grid">
              {page.items.map((review) => (
                <section className="card host-review-card" key={review.id}>
                  <div className="host-review-property">
                    <Link to={`/host/listings/${review.listing_id}/preview`}>
                      {review.listing_title}
                    </Link>
                    <time dateTime={review.published_at ?? review.submitted_at}>
                      {new Date(
                        review.published_at ?? review.submitted_at,
                      ).toLocaleDateString(undefined, {
                        month: "short",
                        year: "numeric",
                      })}
                    </time>
                  </div>
                  <ReviewContent review={review} />
                </section>
              ))}
            </div>
          )}
          {page.next_cursor && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void more()}
            >
              {busy ? "Loading…" : "Load more reviews"}
            </Button>
          )}
        </>
      )}
    </main>
  );
}
