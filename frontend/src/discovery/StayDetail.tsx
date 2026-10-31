import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { ErrorState } from "../components/ui";
import {
  discoveryApi,
  type PublicDetail,
  type Quote,
  type PriceBreakdown,
} from "./api";
import { PublicLocation } from "../location/PublicLocation";
import { PublicPhotos } from "./PublicPhotos";
import { StayAvailability } from "./StayAvailability";
import { ListingReviews } from "../reviews/ListingReviews";
import { SearchForm } from "./SearchForm";
import {
  searchValues,
  searchQuery,
  validateSearch,
  formatDate,
  type SearchValues,
} from "./dates";
import { formatEUR } from "../listings/form";
export function PriceLines({ price }: { price: PriceBreakdown }) {
  return (
    <dl className="quote-lines">
      <div>
        <dt>
          {formatEUR(price.nightly_minor)} × {price.nights} nights
        </dt>
        <dd>{formatEUR(price.nights_minor)}</dd>
      </div>
      <div>
        <dt>Cleaning fee</dt>
        <dd>{formatEUR(price.cleaning_minor)}</dd>
      </div>
      <div>
        <dt>Subtotal</dt>
        <dd>{formatEUR(price.subtotal_minor)}</dd>
      </div>
      <div>
        <dt>StayHub service fee · 14%</dt>
        <dd>{formatEUR(price.guest_fee_minor)}</dd>
      </div>
      <div className="quote-total">
        <dt>Total (EUR)</dt>
        <dd>{formatEUR(price.total_minor)}</dd>
      </div>
    </dl>
  );
}
export function StayDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const [data, setData] = useState<{
    id: string;
    listing: PublicDetail;
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [quote, setQuote] = useState<{
    query: string;
    id: string;
    value: Quote;
  } | null>(null);
  const [quoteError, setQuoteError] = useState<{
    query: string;
    message: string;
  } | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const quoteGeneration = useRef(0);
  const values = searchValues(params);
  const bookingDraft = useRef<{ query: string; values: SearchValues } | null>(
    null,
  );
  const [quoteDirty, setQuoteDirty] = useState(false);
  useEffect(() => {
    if (!id) return;
    let active = true;
    const controller = new AbortController();
    void discoveryApi
      .detail(id, controller.signal)
      .then((result) => {
        if (active) {
          setData({ id, listing: result.listing });
          setError("");
        }
      })
      .catch((e) => {
        if (active)
          setError(
            e instanceof Error ? e.message : "Could not load this stay.",
          );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [id, attempt]);
  useEffect(() => {
    const generation = ++quoteGeneration.current;
    const selected = searchValues(new URLSearchParams(query));
    if (!id || Object.keys(validateSearch(selected, true)).length) return;
    let active = true;
    void discoveryApi
      .quote(id, {
        check_in: selected.check_in,
        check_out: selected.check_out,
        guests: Number(selected.guests),
      })
      .then((result) => {
        if (active && generation === quoteGeneration.current) {
          setQuote({ query, id, value: result.quote });
          setQuoteError(null);
          setQuoteBusy(false);
          setQuoteDirty(false);
        }
      })
      .catch((e) => {
        if (active && generation === quoteGeneration.current) {
          setQuoteError({
            query,
            message:
              e instanceof ApiError && e.details.field_errors
                ? `${e.message} ${Object.values(e.details.field_errors).flat().join(" ")}`
                : e instanceof Error
                  ? e.message
                  : "Could not check the price.",
          });
          setQuoteBusy(false);
        }
      });
    return () => {
      active = false;
    };
  }, [id, query]);
  async function check(next: SearchValues) {
    const committed = new URLSearchParams(params);
    for (const key of [
      "destination",
      "check_in",
      "check_out",
      "guests",
      "cursor",
    ])
      committed.delete(key);
    new URLSearchParams(searchQuery(next)).forEach((value, key) =>
      committed.set(key, value),
    );
    const nextQuery = committed.toString();
    if (nextQuery !== query) {
      setParams(new URLSearchParams(nextQuery));
      return;
    }
    const generation = ++quoteGeneration.current;
    setQuoteBusy(true);
    setQuoteError(null);
    try {
      const result = await discoveryApi.quote(id!, {
        check_in: next.check_in,
        check_out: next.check_out,
        guests: Number(next.guests),
      });
      if (generation === quoteGeneration.current) {
        setQuote({ query, id: id!, value: result.quote });
        setQuoteDirty(false);
        setQuoteError(null);
        setQuoteBusy(false);
      }
    } catch (e) {
      if (generation === quoteGeneration.current)
        setQuoteError({
          query,
          message:
            e instanceof ApiError && e.details.field_errors
              ? `${e.message} ${Object.values(e.details.field_errors).flat().join(" ")}`
              : e instanceof Error
                ? e.message
                : "Could not check the price.",
        });
    } finally {
      if (generation === quoteGeneration.current) setQuoteBusy(false);
    }
  }
  if (error)
    return (
      <main className="page-container">
        <ErrorState
          message={error}
          retry={() => {
            setError("");
            setAttempt(attempt + 1);
          }}
        />
      </main>
    );
  const listing = data && data.id === id ? data.listing : null;
  if (!listing)
    return (
      <main className="page-container" role="status">
        Loading this stay…
      </main>
    );
  const currentQuote =
    quote?.query === query && quote.id === id ? quote.value : null;
  const currentQuoteError =
    quoteError?.query === query ? quoteError.message : null;
  return (
    <main className="page-container public-detail">
      <Link className="back-to-stays" to={`/stays${query ? `?${query}` : ""}`}>
        ← Back to stays
      </Link>
      <div className="preview-heading">
        <h1>{listing.title}</h1>
        <div>
          <span className="new-label">New</span>
          <span>{listing.destination}</span>
        </div>
        {listing.demo_label && (
          <p className="demo-label">{listing.demo_label}</p>
        )}
      </div>
      <PublicPhotos
        key={`${listing.id}-${listing.photos[0]?.url ?? ""}`}
        listingId={listing.id}
        photos={listing.photos}
        title={listing.title}
        gallery
      />
      <div className="public-detail-columns">
        <div>
          <section className="preview-section host-introduction">
            <div>
              <h2>
                {listing.property_type === "room"
                  ? "Private room"
                  : `Entire ${listing.property_type}`}{" "}
                hosted by {listing.host_name}
              </h2>
              <p>
                {listing.capacity} {listing.capacity === 1 ? "guest" : "guests"}{" "}
                · {listing.bedrooms}{" "}
                {listing.bedrooms === 1 ? "bedroom" : "bedrooms"} ·{" "}
                {listing.beds} {listing.beds === 1 ? "bed" : "beds"} ·{" "}
                {listing.baths} {listing.baths === 1 ? "bathroom" : "bathrooms"}
              </p>
            </div>
            <span className="avatar large" aria-hidden="true">
              {listing.host_name.slice(0, 2).toUpperCase()}
            </span>
          </section>
          <section className="preview-section">
            <h2>About this place</h2>
            <p className="preserve-lines">{listing.description}</p>
          </section>
          <section className="preview-section">
            <h2>What this place offers</h2>
            <ul className="amenity-list">
              {listing.amenities.map((amenity) => (
                <li key={amenity}>✓ {amenity}</li>
              ))}
            </ul>
          </section>
          <section className="preview-section">
            <h2>House rules</h2>
            <p>
              Check-in {listing.check_in_time} · Check-out{" "}
              {listing.check_out_time}
            </p>
            <p className="muted">
              Local times in {listing.timezone} · {listing.capacity} guests
              maximum
            </p>
            <ul>
              {listing.house_rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </section>
          <section className="preview-section">
            <h2>Cancellation policy · {listing.policy.name}</h2>
            <p>{listing.policy.terms}</p>
            <p className="muted">
              Policy version {listing.policy.version}. These terms will be
              included in a future booking.
            </p>
          </section>
          <ListingReviews
            key={`reviews-${listing.id}`}
            listingId={listing.id}
          />
          <StayAvailability
            key={`${listing.id}-${query}`}
            listing={listing}
            checkIn={values.check_in}
            checkOut={values.check_out}
            onApply={(range) =>
              void check({
                ...(bookingDraft.current?.query === query
                  ? bookingDraft.current.values
                  : values),
                ...range,
              })
            }
          />
          <section className="preview-section">
            <h2>Where you’ll be</h2>
            <p>{listing.destination}</p>
            <PublicLocation key={listing.id} listingId={listing.id} />
          </section>
        </div>
        <aside className="public-quote card">
          <h2>
            {formatEUR(listing.nightly_minor)} <span>/ night</span>
          </h2>
          <SearchForm
            key={query}
            initial={values}
            compact
            requireDates
            schedule={listing}
            onSubmit={(next) => void check(next)}
            busy={quoteBusy}
            onDirty={(next) => {
              bookingDraft.current = { query, values: next };
              quoteGeneration.current++;
              setQuote(null);
              setQuoteError(null);
              setQuoteDirty(true);
              setQuoteBusy(false);
            }}
          />
          {currentQuoteError ? (
            <ErrorState
              message={currentQuoteError}
              retry={() => void check(values)}
            />
          ) : currentQuote ? (
            <>
              <PriceLines price={currentQuote} />
              <p className="quote-dates">
                {formatDate(currentQuote.check_in)} –{" "}
                {formatDate(currentQuote.check_out)} · {currentQuote.guests}{" "}
                guests
              </p>
              <p className="field-help">
                Scheduled check-in{" "}
                {new Intl.DateTimeFormat("en-GB", {
                  dateStyle: "medium",
                  timeStyle: "short",
                  timeZone: listing.timezone,
                }).format(new Date(currentQuote.scheduled_check_in))}{" "}
                ({listing.timezone}).
              </p>
            </>
          ) : values.check_in &&
            values.check_out &&
            !Object.keys(validateSearch(values, true)).length &&
            !quoteDirty ? (
            <p role="status">Checking availability and price…</p>
          ) : (
            <p className="muted">
              Choose dates and guests, then check the full stay price.
            </p>
          )}
          {currentQuote && !quoteDirty && !currentQuoteError && (
            <Link
              className="button booking-action"
              to={`/checkout/${listing.id}?${query}`}
            >
              Reserve
            </Link>
          )}
          <p className="booking-notice">
            Checking a price does not reserve dates or charge you. Review your
            trip before simulated payment.
          </p>
        </aside>
      </div>
    </main>
  );
}
