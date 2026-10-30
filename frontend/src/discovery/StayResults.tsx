import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { ApiError } from "../api/client";
import { discoveryApi, type PublicSummary } from "./api";
import { SearchForm } from "./SearchForm";
import { searchValues } from "./dates";
import { PublicPhotos } from "./PublicPhotos";
import { formatEUR } from "../listings/form";
export function StayResults({ explore = false }: { explore?: boolean }) {
  const [params] = useSearchParams();
  const query = params.toString();
  const [data, setData] = useState<{
    query: string;
    items: PublicSummary[];
    cursor: string | null;
  } | null>(null);
  const [failure, setFailure] = useState<{
    query: string;
    message: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState("");
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void discoveryApi
      .search(query, controller.signal)
      .then((result) => {
        if (active) {
          setData({ query, items: result.items, cursor: result.next_cursor });
          setFailure(null);
        }
      })
      .catch((error) => {
        if (active)
          setFailure({
            query,
            message:
              error instanceof ApiError && error.details.field_errors
                ? `${error.message} ${Object.values(error.details.field_errors).flat().join(" ")}`
                : error instanceof Error
                  ? error.message
                  : "Could not load stays.",
          });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [query, attempt]);
  const current = data?.query === query ? data : null;
  const error = failure?.query === query ? failure.message : null;
  async function more() {
    if (!current?.cursor) return;
    setMoreBusy(true);
    setMoreError("");
    try {
      const next = new URLSearchParams(query);
      next.set("cursor", current.cursor);
      const result = await discoveryApi.search(next.toString());
      setData((previous) =>
        previous?.query === query
          ? {
              ...previous,
              items: [
                ...previous.items,
                ...result.items.filter(
                  (item) => !previous.items.some((old) => old.id === item.id),
                ),
              ],
              cursor: result.next_cursor,
            }
          : previous,
      );
    } catch (e) {
      setMoreError(
        e instanceof Error ? e.message : "Could not load more stays.",
      );
    } finally {
      setMoreBusy(false);
    }
  }
  const values = searchValues(params);
  return (
    <main className="page-container discovery-page">
      <div className="page-heading">
        <h1>
          {explore ? "Find a place to stay" : "Stays for your next chapter"}
        </h1>
        <p>
          {explore
            ? "Thoughtful places. Room to feel at home."
            : "Explore places that fit your plans."}
        </p>
      </div>
      <SearchForm key={query} initial={values} />
      {error ? (
        <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
      ) : !current ? (
        <div className="stay-loading" role="status">
          <span />
          Loading stays…
        </div>
      ) : !current.items.length && !current.cursor ? (
        <EmptyState
          title="No stays match your plans"
          action={
            <Link className="button secondary" to="/stays">
              Browse all stays
            </Link>
          }
        >
          Try a different destination, fewer guests or another set of dates.
        </EmptyState>
      ) : (
        <>
          <div className="results-heading">
            <h2>
              {explore
                ? "Places to make your own"
                : `${current.items.length} ${current.items.length === 1 ? "stay" : "stays"}${current.cursor ? " loaded" : ""}`}
            </h2>
            <p className="muted">
              {values.check_in && values.check_out
                ? "Stay totals include cleaning and the StayHub service fee."
                : "Choose dates to see the full stay price."}
            </p>
          </div>
          <div className={explore ? "public-stay-grid" : "public-stay-results"}>
            {current.items.map((listing) => (
              <article
                key={listing.id}
                className={`public-stay-card ${explore ? "" : "result-row"}`}
              >
                <div className="stay-photo-link">
                  <PublicPhotos
                    key={`${listing.id}-${listing.photos[0]?.url ?? ""}`}
                    listingId={listing.id}
                    photos={listing.photos}
                    title={listing.title}
                  />
                </div>
                <div className="public-stay-content">
                  <div className="stay-card-location">
                    <span>{listing.destination}</span>
                    <span className="new-label">New</span>
                  </div>
                  <Link to={`/stays/${listing.id}${query ? `?${query}` : ""}`}>
                    <h2>{listing.title}</h2>
                  </Link>
                  <p className="muted">
                    {listing.property_type === "room"
                      ? "Private room"
                      : `Entire ${listing.property_type}`}{" "}
                    · {listing.capacity} guests · {listing.beds}{" "}
                    {listing.beds === 1 ? "bed" : "beds"} · {listing.baths}{" "}
                    {listing.baths === 1 ? "bath" : "baths"}
                  </p>
                  {listing.demo_label && (
                    <p className="demo-label">{listing.demo_label}</p>
                  )}
                  <div className="stay-card-price">
                    <p>
                      <strong>{formatEUR(listing.nightly_minor)}</strong>
                      <span> / night</span>
                    </p>
                    {listing.stay_price && (
                      <p>
                        <strong>
                          {formatEUR(listing.stay_price.total_minor)}
                        </strong>
                        <span> total · {listing.stay_price.nights} nights</span>
                      </p>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
          {moreError && (
            <ErrorState message={moreError} retry={() => void more()} />
          )}{" "}
          {current.cursor && (
            <Button
              variant="secondary"
              disabled={moreBusy}
              onClick={() => void more()}
            >
              {moreBusy ? "Loading…" : "Load more stays"}
            </Button>
          )}
        </>
      )}
    </main>
  );
}
