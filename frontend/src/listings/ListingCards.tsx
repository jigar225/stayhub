import { useEffect, useState } from "react";
import { Link } from "react-router";
import { listingsApi, type Listing } from "./api";
import { formatEUR } from "./form";
import { PhotoImage } from "./PhotoImage";
import { Button, EmptyState, ErrorState } from "../components/ui";
export function StatusBadge({ status }: { status: Listing["status"] }) {
  return (
    <span className={`badge listing-status ${status}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
export function ListingCards() {
  const [items, setItems] = useState<Listing[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  useEffect(() => {
    let active = true;
    void listingsApi
      .list()
      .then((data) => {
        if (active) {
          setItems(data.items);
          setCursor(data.next_cursor);
        }
      })
      .catch((e) => {
        if (active)
          setError(e instanceof Error ? e.message : "Could not load listings.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  async function more() {
    if (!cursor) return;
    setLoading(true);
    setError("");
    try {
      const data = await listingsApi.list(cursor);
      setItems((current) => [
        ...current,
        ...data.items.filter(
          (item) => !current.some((existing) => existing.id === item.id),
        ),
      ]);
      setCursor(data.next_cursor);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load more listings.",
      );
    } finally {
      setLoading(false);
    }
  }
  async function create() {
    setCreating(true);
    setCreateError("");
    try {
      const data = await listingsApi.create();
      window.location.assign(`/host/listings/${data.listing.id}/edit`);
    } catch (e) {
      setCreateError(
        e instanceof Error
          ? e.message
          : "Could not create a draft. If the connection dropped, reload your listings before trying again.",
      );
      setCreating(false);
    }
  }
  return (
    <main className="host-content">
      <div className="listing-page-heading">
        <div>
          <h1>Listings</h1>
          <p className="muted">
            Your places, from first draft to ready for guests.
          </p>
        </div>
        <Button onClick={() => void create()} disabled={creating}>
          {creating ? "Creating…" : "+ Create listing"}
        </Button>
      </div>
      {createError && (
        <ErrorState
          message={`${createError} Reload your listings before creating another draft.`}
          retry={() => {
            setCreateError("");
            setAttempt(attempt + 1);
          }}
        />
      )}
      {error && (
        <ErrorState
          message={error}
          retry={() => {
            setError("");
            setLoading(true);
            setAttempt(attempt + 1);
          }}
        />
      )}
      {loading && !items.length ? (
        <p role="status">Loading your listings…</p>
      ) : !items.length && !error ? (
        <EmptyState
          title="Make room for your first listing"
          action={
            <Button onClick={() => void create()} disabled={creating}>
              Create listing
            </Button>
          }
        >
          Start with the basics. Save your progress as a draft and publish when
          your place is ready.
        </EmptyState>
      ) : (
        <div className="listing-grid">
          {items.map((listing) => (
            <article className="listing-card" key={listing.id}>
              <div className="listing-card-photo">
                {listing.photos[0] ? (
                  <PhotoImage
                    listingId={listing.id}
                    photo={listing.photos[0]}
                    alt={listing.title ?? "Your listing"}
                  />
                ) : (
                  <div className="photo-placeholder">
                    <span aria-hidden="true">⌂</span>
                    <span>Add your first photo</span>
                  </div>
                )}
              </div>
              <div className="listing-card-body">
                <div className="listing-card-title">
                  <h2>{listing.title ?? "Untitled listing"}</h2>
                  <StatusBadge status={listing.status} />
                </div>
                <p className="muted">
                  {listing.property_type ?? "Property type not set"}
                  {listing.capacity ? ` · ${listing.capacity} guests` : ""}
                </p>
                <p>
                  <strong>{formatEUR(listing.nightly_minor)}</strong>
                  {listing.nightly_minor !== null && (
                    <span className="muted"> / night</span>
                  )}
                </p>
                <div className="listing-card-actions">
                  <Link
                    className="button secondary"
                    to={`/host/listings/${listing.id}/edit`}
                  >
                    {listing.status === "draft" ? "Resume draft" : "Edit"}
                  </Link>
                  <Link
                    className="button secondary"
                    to={`/host/listings/${listing.id}/preview`}
                  >
                    Preview
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      {cursor && (
        <Button
          variant="secondary"
          disabled={loading}
          onClick={() => void more()}
        >
          {loading ? "Loading…" : "Load more"}
        </Button>
      )}
    </main>
  );
}
