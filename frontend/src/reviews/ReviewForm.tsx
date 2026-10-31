import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { useSession } from "../auth/useSession";
import { Button, ErrorState } from "../components/ui";
import { bookingError } from "../booking/api";
import {
  reviewApi,
  reviewCategories,
  type PartyReviews,
  type Review,
} from "./api";

export function ReviewContent({ review }: { review: Review }) {
  return (
    <article className="review-content">
      <p>
        <strong>{review.author_name}</strong>
        {review.overall !== null && <> · {review.overall} / 5</>}
      </p>
      <p className="review-text">{review.text}</p>
      {Object.keys(review.categories).length > 0 && (
        <dl className="review-category-summary">
          {Object.entries(review.categories).map(([key, value]) => (
            <div key={key}>
              <dt>
                {reviewCategories[key as keyof typeof reviewCategories] ?? key}
              </dt>
              <dd>{value} / 5</dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}

export function ReviewForm() {
  const { id = "", reservationId = "" } = useParams();
  const rid = id || reservationId;
  const { user } = useSession();
  if (!user)
    return (
      <main className="page-container">
        <p>Sign in to review your reservation.</p>
      </main>
    );
  return <ReviewEditor key={`${user.id}:${rid}`} rid={rid} actorId={user.id} />;
}

function ReviewEditor({ rid, actorId }: { rid: string; actorId: string }) {
  const [data, setData] = useState<{ key: string; value: PartyReviews } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const key = `${actorId}:${rid}`;
  useEffect(() => {
    let active = true;
    void reviewApi
      .party(rid)
      .then((value) => {
        if (active) {
          setData({ key, value });
          setError("");
          setBusy(false);
        }
      })
      .catch((e) => {
        if (active) {
          setError(bookingError(e));
          setBusy(false);
        }
      });
    return () => {
      active = false;
    };
  }, [rid, key, attempt]);
  const current = data?.key === key ? data.value : null;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current?.eligible || busy || !confirmed) return;
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const body =
        current.role === "guest"
          ? {
              text,
              overall: Number(values.get("overall")),
              categories: Object.fromEntries(
                Object.keys(reviewCategories).map((name) => [
                  name,
                  Number(values.get(name)),
                ]),
              ),
            }
          : { text };
      const value = await reviewApi.submit(rid, body);
      setData({ key, value });
    } catch (e) {
      // Resolve an unknown submission outcome before allowing another submission.
      try {
        const value = await reviewApi.party(rid);
        if (value.own) {
          setData({ key, value });
          return;
        }
      } catch {
        /* Keep the original actionable error. */
      }
      setError(bookingError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="page-container review-page">
      <Link to={`/trips/${rid}`}>← Reservation</Link>
      <div className="page-heading">
        <h1>
          {current?.role === "host" ? "Review your guest" : "Review your stay"}
        </h1>
        {current && <p>{current.listing_title}</p>}
      </div>
      {error && (
        <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
      )}
      {!current && !error && <p role="status">Loading review window…</p>}
      {current && (
        <>
          <section className="card review-explanation">
            <h2>Honest reviews, shared fairly</h2>
            <p>
              Reviews stay private until both parties submit or the 14-day
              window ends. Your submitted review cannot be edited.
            </p>
            {current.deadline && (
              <p>
                Window closes{" "}
                {new Date(current.deadline).toLocaleString("en-GB", {
                  timeZone: "UTC",
                  dateStyle: "medium",
                  timeStyle: "short",
                })}{" "}
                UTC.
              </p>
            )}
          </section>
          {current.eligible && (
            <form
              className="card review-form"
              onSubmit={(event) => void submit(event)}
            >
              {current.role === "guest" && (
                <fieldset className="review-rating-fields">
                  <legend>Rate your stay</legend>
                  {Object.entries({
                    overall: "Overall rating",
                    ...reviewCategories,
                  }).map(([name, label]) => (
                    <div className="field" key={name}>
                      <label htmlFor={`review-${name}`}>{label}</label>
                      <select
                        id={`review-${name}`}
                        name={name}
                        required
                        defaultValue=""
                      >
                        <option value="" disabled>
                          Select a rating
                        </option>
                        {[1, 2, 3, 4, 5].map((rating) => (
                          <option value={rating} key={rating}>
                            {rating} / 5
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </fieldset>
              )}
              <div className="field">
                <label htmlFor="review-text">
                  {current.role === "guest"
                    ? "Public review"
                    : "Review of your guest"}
                </label>
                <textarea
                  id="review-text"
                  name="text"
                  required
                  minLength={1}
                  maxLength={3000}
                  rows={4}
                  aria-describedby="review-text-help"
                  placeholder={
                    current.role === "guest"
                      ? "What was your stay like?"
                      : "How was your experience hosting this guest?"
                  }
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                />
                <div className="review-text-help" id="review-text-help">
                  <span>
                    Please keep private contact details out of your review.
                  </span>
                  <span className="review-character-count">
                    {text.length.toLocaleString()} / 3,000
                  </span>
                </div>
              </div>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                  required
                />{" "}
                I understand my submitted review cannot be edited.
              </label>
              <Button type="submit" disabled={busy || !confirmed}>
                {busy ? "Submitting…" : "Submit review"}
              </Button>
            </form>
          )}
          {current.status === "not_completed" && (
            <p className="card" role="status">
              Reviews open after a stay has completed. Cancelled and declined
              reservations cannot be reviewed.
            </p>
          )}
          {current.status === "closed" && (
            <p className="card" role="status">
              The review window has closed.
            </p>
          )}
          {current.own && (
            <section className="card">
              <h2>Your submitted review</h2>
              <p role="status">
                {current.own.published_at
                  ? "Published"
                  : "Saved privately. It will be published when both parties submit or the window closes."}
              </p>
              {!current.own.published_at && (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    setAttempt((value) => value + 1);
                  }}
                >
                  {busy ? "Refreshing…" : "Refresh review status"}
                </Button>
              )}
              <ReviewContent review={current.own} />
            </section>
          )}
          {current.counterpart && (
            <section className="card">
              <h2>
                {current.role === "guest"
                  ? "Your host’s review"
                  : "Your guest’s review"}
              </h2>
              <ReviewContent review={current.counterpart} />
            </section>
          )}
        </>
      )}
    </main>
  );
}
