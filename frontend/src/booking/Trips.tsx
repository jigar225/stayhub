import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { TripPhoto } from "./TripPhoto";
import { CancellationActions } from "./Cancellation";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { formatDate } from "../discovery/dates";
import { PublicPhotos } from "../discovery/PublicPhotos";
import type { PublicPhoto } from "../discovery/api";
import { PriceLines } from "../discovery/StayDetail";
import { formatEUR } from "../listings/form";
import {
  bookingApi,
  bookingError,
  type Reservation,
  type ReservationPage,
} from "./api";
export function Status({ reservation }: { reservation: Reservation }) {
  return (
    <span className={`reservation-status ${reservation.state}`}>
      {reservation.state === "pending"
        ? "Pending host response"
        : reservation.state === "declined" && reservation.reason === "expired"
          ? "Expired · fully refunded"
          : reservation.state === "declined"
            ? "Declined · fully refunded"
            : reservation.state === "cancelled_by_guest"
              ? "Cancelled by guest"
              : reservation.state === "cancelled_by_host"
                ? "Cancelled by host · fully refunded"
                : reservation.state === "checked_in"
                  ? "Checked in"
                  : reservation.state === "completed"
                    ? "Completed"
                    : "Confirmed"}
    </span>
  );
}
export function TripCard({ reservation: r }: { reservation: Reservation }) {
  return (
    <article className="card trip-card trip-card-with-photo">
      <TripPhoto
        key={r.id}
        reservationId={r.id}
        title={r.listing_snapshot.title}
      />
      <div className="trip-card-content">
        <Status reservation={r} />
        <h2>{r.listing_snapshot.title}</h2>
        <p>{r.listing_snapshot.destination}</p>
        <p>
          {formatDate(r.check_in)} – {formatDate(r.check_out)} · {r.guests}{" "}
          guests
        </p>
        <p>
          Reservation <code>{r.code}</code>
        </p>
      </div>
      <div className="trip-card-summary">
        <strong>{formatEUR(r.price.total_minor)}</strong>
        <span>
          Original total · {r.price.nights}{" "}
          {r.price.nights === 1 ? "night" : "nights"}
        </span>
        {r.refund && <span>Refunded {formatEUR(r.refund.amount_minor)}</span>}
        <Link className="button secondary" to={`/trips/${r.id}`}>
          View reservation
        </Link>
        <Link to={`/messages/${r.id}`}>Messages</Link>
        {r.state === "completed" && (
          <Link to={`/trips/${r.id}/review`}>Review this stay</Link>
        )}
      </div>
    </article>
  );
}
export function Trips() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "upcoming";
  const [data, setData] = useState<{
    category: string;
    page: ReservationPage;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const generation = useRef<{ active: boolean } | null>(null);
  useEffect(() => {
    const request = { active: true };
    generation.current = request;
    void bookingApi
      .trips(category)
      .then((page) => {
        if (request.active) {
          setBusy(false);
          setData({ category, page });
          setError("");
        }
      })
      .catch((e) => {
        if (request.active) {
          setBusy(false);
          setData(null);
          setError(bookingError(e));
        }
      });
    return () => {
      request.active = false;
    };
  }, [category, attempt]);
  const page = data?.category === category ? data.page : null;
  async function more() {
    if (!page?.next_cursor || busy) return;
    const request = generation.current;
    setBusy(true);
    setError("");
    try {
      const next = await bookingApi.trips(category, page.next_cursor);
      if (!request?.active) return;
      setData({
        category,
        page: {
          items: [...page.items, ...next.items],
          next_cursor: next.next_cursor,
        },
      });
    } catch (e) {
      if (request?.active) setError(bookingError(e));
    } finally {
      if (request?.active) setBusy(false);
    }
  }
  return (
    <main className="page-container trips-page">
      <div className="page-heading">
        <h1>Trips</h1>
        <p>Your reservations and simulated payments.</p>
      </div>
      <nav className="trip-tabs" aria-label="Trip categories">
        {["upcoming", "pending", "past", "cancelled", "all"].map((value) => (
          <Button
            key={value}
            variant={category === value ? "primary" : "secondary"}
            onClick={() => {
              setError("");
              setParams({ category: value });
            }}
          >
            {value[0].toUpperCase() + value.slice(1)}
          </Button>
        ))}
      </nav>
      {error && (
        <ErrorState
          message={error}
          retry={() => (page ? void more() : setAttempt(attempt + 1))}
        />
      )}
      {!page && !error ? (
        <p role="status">Loading trips…</p>
      ) : (
        page && (
          <>
            {page.items.length ? (
              <div className="trip-list">
                {page.items.map((r) => (
                  <TripCard reservation={r} key={r.id} />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No trips in this category"
                action={
                  <Link to="/stays" className="button secondary">
                    Explore stays
                  </Link>
                }
              >
                Your real reservations will appear here. No trips have been
                added to this category.
              </EmptyState>
            )}
            {page.next_cursor && (
              <Button disabled={busy} onClick={() => void more()}>
                {busy ? "Loading…" : "Load more trips"}
              </Button>
            )}
          </>
        )
      )}
    </main>
  );
}
export function TripDetail() {
  const { id = "" } = useParams();
  const [data, setData] = useState<{
    id: string;
    reservation: Reservation;
  } | null>(null);
  const [photos, setPhotos] = useState<{
    id: string;
    items: PublicPhoto[];
  } | null>(null);
  const [error, setError] = useState("");
  const [photoError, setPhotoError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void bookingApi
      .detail(id)
      .then((result) => {
        if (active) {
          setData({ id, reservation: result.reservation });
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(bookingError(e));
      });
    void bookingApi
      .photos(id)
      .then((result) => {
        if (active) {
          setPhotos({ id, items: result.items });
          setPhotoError("");
        }
      })
      .catch((e) => {
        if (active) setPhotoError(bookingError(e));
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);
  const r = data?.id === id ? data.reservation : null;
  if (error)
    return (
      <main className="page-container">
        <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
      </main>
    );
  if (!r)
    return (
      <main className="page-container" role="status">
        Loading reservation…
      </main>
    );
  return (
    <main className="page-container reservation-detail">
      <Link to="/trips">← All trips</Link>
      <div className="page-heading">
        <h1>
          {r.state === "pending"
            ? "Your request is awaiting the host"
            : r.state === "confirmed"
              ? "Your stay is confirmed"
              : r.state === "checked_in"
                ? "Your stay is in progress"
                : r.state === "completed"
                  ? "Your stay is complete"
                  : r.state.startsWith("cancelled")
                    ? "Your reservation is cancelled"
                    : "Your request was declined"}
        </h1>
        <Status reservation={r} />
        <p>
          Reservation code <code>{r.code}</code>
        </p>
        <div className="reservation-communication-actions">
          <Link className="button secondary" to={`/messages/${r.id}`}>
            Message the other party
          </Link>
          {r.state === "completed" && (
            <Link className="button secondary" to={`/trips/${r.id}/review`}>
              Review this stay
            </Link>
          )}
        </div>
      </div>
      {photoError ? (
        <ErrorState
          message={photoError}
          retry={() => setAttempt(attempt + 1)}
        />
      ) : (
        photos?.id === id && (
          <PublicPhotos
            key={id}
            listingId={r.listing_id}
            photos={photos.items}
            title={r.listing_snapshot.title}
            renewPhotos={() => bookingApi.photos(id)}
            gallery
          />
        )
      )}
      <div className="checkout-columns">
        <div>
          <section className="preview-section">
            <h2>{r.listing_snapshot.title}</h2>
            <p>
              {r.listing_snapshot.destination} ·{" "}
              {r.listing_snapshot.property_type} · hosted by{" "}
              {r.listing_snapshot.host_name}
            </p>
            <p>{r.listing_snapshot.description}</p>
            <dl className="trip-facts">
              <div>
                <dt>Dates</dt>
                <dd>
                  {formatDate(r.check_in)} – {formatDate(r.check_out)}
                </dd>
              </div>
              <div>
                <dt>Guests</dt>
                <dd>{r.guests}</dd>
              </div>
              <div>
                <dt>Check-in</dt>
                <dd>
                  {new Intl.DateTimeFormat("en-GB", {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: r.timezone,
                  }).format(new Date(r.scheduled_check_in))}{" "}
                  ({r.timezone})
                </dd>
              </div>
            </dl>
            {r.request_deadline && r.state === "pending" && (
              <p className="deadline-notice">
                Host response due{" "}
                {new Intl.DateTimeFormat("en-GB", {
                  dateStyle: "medium",
                  timeStyle: "short",
                  timeZone: r.timezone,
                }).format(new Date(r.request_deadline))}{" "}
                ({r.timezone}). Your simulated payment is charged. A decline or
                expiry refunds it in full.
              </p>
            )}
            {r.reason && <p>Reason: {r.reason}</p>}
          </section>
          <section className="preview-section">
            <h2>Booked house rules</h2>
            <ul>
              {r.listing_snapshot.house_rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
            <h2>Cancellation policy · {r.policy.name}</h2>
            <p>{r.policy.terms}</p>
            <p className="muted">Booked policy version {r.policy.version}.</p>
          </section>
          <CancellationActions
            key={`${r.id}-${r.state}`}
            reservation={r}
            onUpdated={() => setAttempt(attempt + 1)}
          />
        </div>
        <aside className="card checkout-price">
          <h2>Payment details</h2>
          <PriceLines price={r.price} />
          <p>
            Simulated charge:{" "}
            <strong>{formatEUR(r.payment.amount_minor)}</strong>
          </p>
          <p className="field-help">
            Paid{" "}
            {new Date(r.payment.paid_at).toLocaleString("en-GB", {
              timeZone: r.timezone,
            })}{" "}
            ({r.timezone})
          </p>
          {r.refund && (
            <section className="refund-record">
              <h3>
                {r.refund.amount_minor === r.payment.amount_minor
                  ? "Full refund"
                  : "Recorded refund"}
              </h3>
              <p>Nights {formatEUR(r.refund.nights_minor)}</p>
              <p>Cleaning {formatEUR(r.refund.cleaning_minor)}</p>
              <p>Guest service fee {formatEUR(r.refund.guest_fee_minor)}</p>
              <strong>Total refunded {formatEUR(r.refund.amount_minor)}</strong>
              <p>{r.refund.reason}</p>
            </section>
          )}
          <p className="field-help">
            This reservation uses the terms saved when you paid.
          </p>
        </aside>
      </div>
    </main>
  );
}
