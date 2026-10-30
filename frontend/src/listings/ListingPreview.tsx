import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { listingsApi, type Listing, type Policy } from "./api";
import { formatEUR } from "./form";
import { PhotoImage } from "./PhotoImage";
import { StatusBadge } from "./ListingCards";
import { ErrorState } from "../components/ui";
export function ListingPreview() {
  const { id } = useParams();
  const [listing, setListing] = useState<Listing | null>(null);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!id) return;
    let active = true;
    void Promise.all([listingsApi.read(id), listingsApi.policies()])
      .then(([data, policyData]) => {
        if (active) {
          setListing(data.listing);
          setPolicies(policyData.items);
        }
      })
      .catch((e) => {
        if (active)
          setError(e instanceof Error ? e.message : "Could not load preview.");
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);
  if (error)
    return (
      <main className="host-content">
        <ErrorState
          message={error}
          retry={() => {
            setError("");
            setAttempt(attempt + 1);
          }}
        />
      </main>
    );
  if (!listing)
    return (
      <main className="host-content" role="status">
        Loading your listing preview…
      </main>
    );
  return (
    <main className="host-content owner-preview">
      <div className="preview-bar">
        <p>Owner preview · only you can access this page</p>
        <Link
          className="button secondary"
          to={`/host/listings/${listing.id}/edit`}
        >
          Edit listing
        </Link>
      </div>
      <div className="preview-heading">
        <h1>{listing.title ?? "Untitled listing"}</h1>
        <div>
          <StatusBadge status={listing.status} />
          <span>{listing.destination ?? "Destination not set"}</span>
          <span className="muted">New · no reviews yet</span>
        </div>
      </div>
      {listing.photos.length ? (
        <div className="preview-gallery">
          {listing.photos.slice(0, 5).map((photo, index) => (
            <div key={photo.id} className={index === 0 ? "gallery-cover" : ""}>
              <PhotoImage
                listingId={listing.id}
                photo={photo}
                alt={`${listing.title ?? "Listing"}, photo ${index + 1}`}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="preview-no-photos">
          Your listing photos will appear here.
        </div>
      )}
      <div className="preview-columns">
        <div>
          <section className="preview-section">
            <h2>
              {listing.property_type === "room"
                ? "Private room"
                : listing.property_type === "house"
                  ? "Entire house"
                  : listing.property_type === "apartment"
                    ? "Entire apartment"
                    : "Property type not set"}
            </h2>
            <p>
              {listing.capacity ?? "—"} guests · {listing.bedrooms ?? "—"}{" "}
              bedrooms · {listing.beds ?? "—"} beds · {listing.baths ?? "—"}{" "}
              bathrooms
            </p>
          </section>
          <section className="preview-section">
            <h2>About this place</h2>
            <p className="preserve-lines">
              {listing.description ??
                "Add a description to introduce your place."}
            </p>
          </section>
          <section className="preview-section">
            <h2>What this place offers</h2>
            {listing.amenities?.length ? (
              <ul className="amenity-list">
                {listing.amenities.map((amenity) => (
                  <li key={amenity}>✓ {amenity}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">No amenities added yet.</p>
            )}
          </section>
          <section className="preview-section">
            <h2>House rules</h2>
            <p>
              Check-in {listing.check_in_time ?? "15:00"} · Check-out{" "}
              {listing.check_out_time ?? "11:00"}
            </p>
            <p className="muted">
              Times shown in {listing.timezone ?? "the listing timezone"}.
            </p>
            <ul>
              {listing.house_rules?.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </section>
          <section className="preview-section">
            <h2>Cancellation policy</h2>
            <p>
              {policies.find((policy) => policy.id === listing.policy_id)
                ?.name ?? "Not selected"}
              {listing.policy_id ? " · version 1" : ""}
            </p>
          </section>
          <section className="preview-section">
            <h2>Location</h2>
            <p>{listing.destination ?? "Not set"}</p>
            <p className="muted">
              Private owner address: {listing.address ?? "Not set"}
            </p>
          </section>
        </div>
        <aside className="preview-price card">
          <h2>
            {formatEUR(listing.nightly_minor)}
            {listing.nightly_minor !== null && <span> / night</span>}
          </h2>
          <dl>
            <div>
              <dt>Cleaning fee</dt>
              <dd>{formatEUR(listing.cleaning_minor)}</dd>
            </div>
            <div>
              <dt>Booking mode</dt>
              <dd>
                {listing.booking_mode === "request"
                  ? "Request to book"
                  : listing.booking_mode === "instant"
                    ? "Instant booking"
                    : "Not set"}
              </dd>
            </div>
          </dl>
          <p className="muted">
            This is a private preview. Search, availability and reservations
            arrive in later milestones.
          </p>
          <Link className="button secondary" to="/host/listings">
            Back to listings
          </Link>
        </aside>
      </div>
      {listing.photos.length > 5 && (
        <section className="preview-section">
          <h2>More photos</h2>
          <div className="photo-grid">
            {listing.photos.slice(5).map((photo, index) => (
              <div className="photo-tile-image" key={photo.id}>
                <PhotoImage
                  listingId={listing.id}
                  photo={photo}
                  alt={`Listing photo ${index + 6}`}
                />
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
