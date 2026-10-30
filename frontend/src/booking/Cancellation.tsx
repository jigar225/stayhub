import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { readAction, saveAction, clearAction } from "./actionRecovery";
import { ApiError } from "../api/client";
import { refreshBusinessTime, useBusinessTime } from "../api/businessTime";
import { useSession } from "../auth/useSession";
import { Button, ErrorState } from "../components/ui";
import { formatDate } from "../discovery/dates";
import { formatEUR } from "../listings/form";
import {
  bookingApi,
  bookingError,
  type CancellationPreview,
  type Reservation,
} from "./api";
function eligibleCancellation(r: Reservation, now: Date | null) {
  return (
    (r.state === "pending" || r.state === "confirmed") &&
    !!now &&
    now.getTime() < Date.parse(r.scheduled_check_in)
  );
}
export function Cancellation() {
  const { id = "" } = useParams();
  const { user } = useSession();
  return <CancellationBody key={`${user?.id}-${id}`} />;
}
function CancellationBody() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { user } = useSession();
  const operation = `cancel:${id}`;
  const [review, setReview] = useState<{
    id: string;
    reservation: Reservation;
    preview: CancellationPreview;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [needsReview, setNeedsReview] = useState(false);
  const [submission, setSubmission] = useState<{
    token: string;
    key: string;
  } | null>(() => (user ? readAction(operation, user.id) : null));
  const flight = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (submission || needsReview) return;
    let active = true;
    void Promise.all([
      bookingApi.detail(id),
      bookingApi.cancellationPreview(id),
    ])
      .then(([r, p]) => {
        if (active) {
          setReview({ id, reservation: r.reservation, preview: p.preview });
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(bookingError(e));
      });
    return () => {
      active = false;
    };
  }, [id, attempt, submission, needsReview]);
  async function cancel() {
    if (
      flight.current ||
      !user ||
      (!submission && (!review || review.id !== id))
    )
      return;
    const original = submission ?? {
      token: review!.preview.confirmation_token,
      key: crypto.randomUUID(),
    };
    try {
      saveAction(operation, user.id, original);
    } catch {
      setError(
        "Enable session storage to safely recover cancellation before confirming.",
      );
      return;
    }
    setSubmission(original);
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      await bookingApi.cancel(id, original.token, original.key);
      if (!alive.current) return;
      clearAction(operation);
      navigate(`/trips/${id}`, { replace: true });
    } catch (e) {
      if (!alive.current) return;
      const unknown =
        !(e instanceof ApiError) ||
        e.status >= 500 ||
        e.status === 401 ||
        e.details.code === "operation_in_progress";
      if (!unknown) {
        clearAction(operation);
        setNeedsReview(true);
        setReview(null);
        setSubmission(null);
      }
      setError(
        bookingError(e) +
          (unknown
            ? " The outcome is uncertain. Retry the original cancellation."
            : " Review a new cancellation preview before confirming again."),
      );
      void refreshBusinessTime();
    } finally {
      flight.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const current = review?.id === id ? review : null;
  return (
    <main className="page-container cancellation-page">
      <Link to={`/trips/${id}`}>← Reservation details</Link>
      <h1>Cancel this reservation?</h1>
      {error && (
        <ErrorState
          message={error}
          retry={
            !submission
              ? () => {
                  setError("");
                  setNeedsReview(false);
                  setAttempt(attempt + 1);
                }
              : undefined
          }
        />
      )}
      {submission && !current ? (
        <section className="card payment-recovery">
          <h2>Resolve original cancellation</h2>
          <p>
            Your cancellation may already have completed. Retry the original
            submission before reviewing any new refund.
          </p>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => void cancel()}
          >
            {busy ? "Resolving…" : "Retry original cancellation"}
          </Button>
        </section>
      ) : !current && !error ? (
        <p role="status">Calculating your refund from the booked policy…</p>
      ) : (
        current && (
          <div className="checkout-columns">
            <section>
              <h2>{current.reservation.listing_snapshot.title}</h2>
              <p>
                {formatDate(current.reservation.check_in)} –{" "}
                {formatDate(current.reservation.check_out)} ·{" "}
                {current.reservation.guests} guests
              </p>
              <p>
                Reservation <code>{current.reservation.code}</code>
              </p>
              <div className="cancellation-explanation">
                <h2>
                  {current.preview.refund_percent}% refund on nights and guest
                  service fee
                </h2>
                <p>{current.preview.explanation}</p>
                <p>
                  Cleaning is refunded in full before check-in, including when
                  the nights refund is 0%.
                </p>
              </div>
              <p>
                Confirming cancels this reservation and reopens its nights. The
                simulated refund is recorded immediately.
              </p>
              <div className="decision-actions">
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => void cancel()}
                >
                  {busy
                    ? "Cancelling…"
                    : submission
                      ? "Retry original cancellation"
                      : "Cancel reservation"}
                </Button>
                {!submission && (
                  <Link className="button secondary" to={`/trips/${id}`}>
                    Keep reservation
                  </Link>
                )}
              </div>
            </section>
            <aside className="card checkout-price">
              <h2>Refund estimate</h2>
              <dl className="quote-lines">
                <div>
                  <dt>Nights</dt>
                  <dd>{formatEUR(current.preview.nights_refund_minor)}</dd>
                </div>
                <div>
                  <dt>Cleaning</dt>
                  <dd>{formatEUR(current.preview.cleaning_refund_minor)}</dd>
                </div>
                <div>
                  <dt>Guest service fee</dt>
                  <dd>{formatEUR(current.preview.guest_fee_refund_minor)}</dd>
                </div>
                <div className="quote-total">
                  <dt>Total refund (EUR)</dt>
                  <dd>{formatEUR(current.preview.total_refund_minor)}</dd>
                </div>
              </dl>
              <p className="field-help">
                {current.preview.policy_name} · booked policy version{" "}
                {current.preview.policy_version}. If this estimate changes, you
                will review it again before cancellation.
              </p>
            </aside>
          </div>
        )
      )}
    </main>
  );
}
export function CancellationActions({
  reservation: r,
  onUpdated,
}: {
  reservation: Reservation;
  onUpdated: () => void;
}) {
  const { user } = useSession();
  const clock = useBusinessTime();
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [original, setOriginal] = useState<{
    reason: string;
    key: string;
  } | null>(null);
  const flight = useRef(false);
  async function hostCancel() {
    if (flight.current) return;
    if (!original && (!reason.trim() || reason.trim().length > 500)) {
      setError("Enter a cancellation reason of 1–500 characters.");
      return;
    }
    const payload = original ?? {
      reason: reason.trim(),
      key: crypto.randomUUID(),
    };
    setOriginal(payload);
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      await bookingApi.hostCancel(r.id, payload.reason, payload.key);
      setConfirm(false);
      setOriginal(null);
      onUpdated();
    } catch (e) {
      const unknown =
        !(e instanceof ApiError) ||
        e.status >= 500 ||
        e.status === 401 ||
        e.details.code === "operation_in_progress";
      if (!unknown) setOriginal(null);
      setError(bookingError(e));
      void refreshBusinessTime();
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  const eligible = eligibleCancellation(r, clock.now);
  return (
    <>
      {clock.error && (
        <ErrorState message={clock.error} retry={() => void clock.refresh()} />
      )}
      {user?.id === r.guest_id && eligible && (
        <Link className="button danger" to={`/trips/${r.id}/cancel`}>
          Review cancellation
        </Link>
      )}
      {user?.id === r.host_id && r.state === "confirmed" && eligible && (
        <section className="host-cancel">
          <h2>Host cancellation</h2>
          {!confirm ? (
            <Button variant="danger" onClick={() => setConfirm(true)}>
              Cancel as host
            </Button>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void hostCancel();
              }}
            >
              <p>
                Cancelling fully refunds {formatEUR(r.payment.amount_minor)} to
                the guest and releases these dates. You receive no earnings for
                this stay.
              </p>
              <label>
                Cancellation reason
                <textarea
                  maxLength={500}
                  value={reason}
                  disabled={busy || !!original}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              {error && <ErrorState message={error} />}
              <div className="decision-actions">
                <Button variant="danger" disabled={busy}>
                  {busy
                    ? "Cancelling…"
                    : original
                      ? "Retry original host cancellation"
                      : "Confirm host cancellation"}
                </Button>
                {!original && (
                  <Button
                    variant="secondary"
                    type="button"
                    onClick={() => setConfirm(false)}
                  >
                    Keep reservation
                  </Button>
                )}
              </div>
            </form>
          )}
        </section>
      )}
    </>
  );
}
