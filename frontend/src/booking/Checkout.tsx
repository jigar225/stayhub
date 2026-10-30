import { useEffect, useRef, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";
import { ApiError } from "../api/client";
import { useSession } from "../auth/useSession";
import { Button, ErrorState } from "../components/ui";
import { discoveryApi, type PublicDetail, type Quote } from "../discovery/api";
import { searchValues, validateSearch, formatDate } from "../discovery/dates";
import { PublicPhotos } from "../discovery/PublicPhotos";
import { PriceLines } from "../discovery/StayDetail";
import { formatEUR } from "../listings/form";
import { bookingApi, bookingError } from "./api";
import {
  readSubmission,
  saveSubmission,
  clearSubmission,
  type PaySubmission,
} from "./recovery";
export function Checkout() {
  const { user } = useSession();
  const location = useLocation();
  return (
    <CheckoutBody
      key={`${user?.id ?? "anonymous"}-${location.pathname}-${location.search}`}
    />
  );
}
function CheckoutBody() {
  const { listingId = "" } = useParams();
  const [params] = useSearchParams();
  const query = params.toString();
  const values = searchValues(params);
  const { user } = useSession();
  const navigate = useNavigate();
  const [pending, setPending] = useState<PaySubmission | null>(() =>
    user ? readSubmission(user.id) : null,
  );
  const [review, setReview] = useState<{
    listing: PublicDetail;
    quote: Quote;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [refreshNeeded, setRefreshNeeded] = useState(false);
  const flight = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (pending || !user || refreshNeeded) return;
    let active = true;
    const fields = validateSearch(
      searchValues(new URLSearchParams(query)),
      true,
    );
    if (Object.keys(fields).length) return;
    void Promise.all([
      discoveryApi.detail(listingId),
      discoveryApi.quote(listingId, {
        check_in: values.check_in,
        check_out: values.check_out,
        guests: Number(values.guests),
      }),
    ])
      .then(([detail, quote]) => {
        if (active) {
          setReview({ listing: detail.listing, quote: quote.quote });
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(bookingError(e));
      });
    return () => {
      active = false;
    };
  }, [
    listingId,
    query,
    user,
    pending,
    refreshNeeded,
    attempt,
    values.check_in,
    values.check_out,
    values.guests,
  ]);
  async function pay() {
    if (flight.current || !user || (!pending && !review)) return;
    const submission = pending ?? {
      actor: user.id,
      listing: listingId,
      check_in: review!.quote.check_in,
      check_out: review!.quote.check_out,
      guests: review!.quote.guests,
      token: review!.quote.quote_token,
      key: crypto.randomUUID(),
    };
    if (submission.actor !== user.id) {
      clearSubmission();
      setPending(null);
      return;
    }
    // Persist before sending. If storage is unavailable, do not risk a charge
    // whose original idempotency key cannot survive this tab's reload.
    try {
      saveSubmission(submission);
    } catch {
      setError(
        "This tab cannot save payment recovery details. Enable session storage before paying.",
      );
      return;
    }
    setPending(submission);
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await bookingApi.pay(submission.token, submission.key);
      if (!alive.current) return;
      clearSubmission();
      setPending(null);
      navigate(`/trips/${result.reservation.id}`, { replace: true });
    } catch (e) {
      if (!alive.current) return;
      const uncertain =
        !(e instanceof ApiError) ||
        e.status >= 500 ||
        e.details.code === "operation_in_progress" ||
        e.status === 401;
      if (!uncertain) {
        clearSubmission();
        setPending(null);
        setReview(null);
        setRefreshNeeded(true);
      }
      setError(
        bookingError(e) +
          (uncertain
            ? " Your payment outcome is unresolved. Retry the original payment below before starting another booking."
            : " Review a fresh price before paying again."),
      );
    } finally {
      flight.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const invalid = validateSearch(values, true);
  if (!user?.roles.includes("guest"))
    return (
      <main className="page-container">
        <h1>Guest membership required</h1>
        <p>This account cannot make a reservation.</p>
      </main>
    );
  return (
    <main className="page-container checkout-page">
      <Link to={`/stays/${listingId}?${query}`} className="back-to-stays">
        ← Back to stay and dates
      </Link>
      <h1>Confirm and pay</h1>
      {pending ? (
        <section className="card payment-recovery">
          <h2>Resolve your original payment</h2>
          <p>
            A payment may already have completed. Retrying uses the original
            submission and cannot create another charge for that submission.
          </p>
          <p>
            {formatDate(pending.check_in)} – {formatDate(pending.check_out)} ·{" "}
            {pending.guests} guests
          </p>
          {error && <ErrorState message={error} />}
          <Button disabled={busy} onClick={() => void pay()}>
            {busy ? "Resolving payment…" : "Retry original payment"}
          </Button>
        </section>
      ) : Object.keys(invalid).length ? (
        <ErrorState message={Object.values(invalid).join(" ")} />
      ) : error ? (
        <ErrorState
          message={error}
          retry={() => {
            setError("");
            setRefreshNeeded(false);
            setAttempt(attempt + 1);
          }}
        />
      ) : !review ? (
        <p role="status">Loading your current price and booking terms…</p>
      ) : (
        <div className="checkout-columns">
          <div>
            <section className="preview-section">
              <h2>Your trip</h2>
              <h3>{review.listing.title}</h3>
              <p>
                {review.listing.destination} · hosted by{" "}
                {review.listing.host_name}
              </p>
              <dl className="trip-facts">
                <div>
                  <dt>Dates</dt>
                  <dd>
                    {formatDate(review.quote.check_in)} –{" "}
                    {formatDate(review.quote.check_out)}
                  </dd>
                </div>
                <div>
                  <dt>Guests</dt>
                  <dd>{review.quote.guests}</dd>
                </div>
                <div>
                  <dt>Scheduled check-in</dt>
                  <dd>
                    {new Intl.DateTimeFormat("en-GB", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: review.listing.timezone,
                    }).format(new Date(review.quote.scheduled_check_in))}{" "}
                    ({review.listing.timezone})
                  </dd>
                </div>
              </dl>
            </section>
            <section className="preview-section">
              <h2>Cancellation policy · {review.quote.policy.name}</h2>
              <p>{review.quote.policy.terms}</p>
              <p className="muted">
                Policy version {review.quote.policy.version}
              </p>
            </section>
            <section className="preview-section">
              <h2>Ground rules</h2>
              <ul>
                {review.listing.house_rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
              <p>
                By paying, you agree to these house rules and the cancellation
                policy shown here.
              </p>
            </section>
            <section className="preview-section">
              <h2>Simulated payment</h2>
              <p>No real money moves and no card information is collected.</p>
              <p>
                {review.quote.booking_mode === "request"
                  ? "You will be charged in the simulation while the host reviews your request. The host has 24 hours to respond. A decline or expiry gives a full refund."
                  : "This instant booking will be confirmed when payment succeeds."}
              </p>
              <Button
                className="booking-action"
                disabled={busy}
                onClick={() => void pay()}
              >
                {busy
                  ? "Paying…"
                  : `Pay ${formatEUR(review.quote.total_minor)}`}
              </Button>
            </section>
          </div>
          <aside className="card checkout-price">
            <PublicPhotos
              listingId={listingId}
              photos={review.listing.photos}
              title={review.listing.title}
            />
            <h2>{review.listing.title}</h2>
            <p>
              {review.quote.nights} nights · {review.quote.guests} guests
            </p>
            <PriceLines price={review.quote} />
            <p className="field-help">
              A quote does not hold dates. Availability and these exact terms
              are checked again when you pay.
            </p>
          </aside>
        </div>
      )}
    </main>
  );
}
