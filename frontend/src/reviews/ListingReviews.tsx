import { useEffect, useRef, useState } from "react";
import { Button, ErrorState } from "../components/ui";
import { bookingError } from "../booking/api";
import { reviewApi, type ListingReviewPage } from "./api";
import { ReviewContent } from "./ReviewForm";

export function ListingReviews({ listingId }: { listingId: string }) {
  const [data, setData] = useState<{
    id: string;
    page: ListingReviewPage;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const generation = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    generation.current = controller;
    void reviewApi
      .listing(listingId, undefined, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) {
          setData({ id: listingId, page });
          setError("");
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(bookingError(e));
      });
    return () => controller.abort();
  }, [listingId, attempt]);
  const page = data?.id === listingId ? data.page : null;
  async function more() {
    const controller = generation.current;
    if (!page?.next_cursor || busy || !controller) return;
    setBusy(true);
    setError("");
    try {
      const next = await reviewApi.listing(
        listingId,
        page.next_cursor,
        controller.signal,
      );
      if (!controller.signal.aborted)
        setData({
          id: listingId,
          page: { ...next, items: [...page.items, ...next.items] },
        });
    } catch (e) {
      if (!controller.signal.aborted) setError(bookingError(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <section
      className="preview-section listing-reviews"
      aria-labelledby="listing-reviews-title"
    >
      <h2 id="listing-reviews-title">Guest reviews</h2>
      {error && (
        <ErrorState
          message={error}
          retry={() => (page ? void more() : setAttempt(attempt + 1))}
        />
      )}
      {!page && !error && <p role="status">Loading guest reviews…</p>}
      {page && (
        <>
          {page.count === 0 ? (
            <p>No published guest reviews yet.</p>
          ) : (
            <>
              <p>
                <strong>{page.average?.toFixed(2)} / 5</strong> · {page.count}{" "}
                {page.count === 1 ? "review" : "reviews"}
              </p>
              <div className="listing-review-grid">
                {page.items.map((review) => (
                  <ReviewContent review={review} key={review.id} />
                ))}
              </div>
              {page.next_cursor && (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void more()}
                >
                  {busy ? "Loading…" : "More guest reviews"}
                </Button>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
