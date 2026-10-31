import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ChangeEvent,
} from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, login } from "../api/client";
import { useSession } from "../auth/useSession";
import { Button, ErrorState } from "../components/ui";
import {
  listingsApi,
  type DraftFields,
  type Listing,
  type Policy,
} from "./api";
import { changedFields, toForm, type ListingForm } from "./form";
import { PhotoManager } from "./PhotoManager";
import { StatusBadge } from "./ListingCards";
import { LocationEditor } from "../location/LocationEditor";
import { STAY_CATEGORIES } from "../discovery/categories";
import { TimezonePicker } from "./TimezonePicker";
const steps = [
  "The basics",
  "Photos & content",
  "Pricing & rules",
  "Review & publish",
];
type FieldErrors = Record<string, string | string[]>;
function fieldText(value: string | string[] | undefined) {
  return Array.isArray(value) ? value.join(" ") : value;
}
export function ListingWizard() {
  const { id } = useParams();
  const navigate = useNavigate();
  const session = useSession();
  const [originalUser] = useState(session.user?.id);
  const [listing, setListing] = useState<Listing | null>(null);
  const photoBaseline = useRef<Listing | null>(null);
  useEffect(() => {
    photoBaseline.current = listing;
  }, [listing]);
  const [form, setForm] = useState<ListingForm | null>(null);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [stale, setStale] = useState(false);
  const [latest, setLatest] = useState<Listing | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [reauthEmail, setReauthEmail] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthError, setReauthError] = useState("");
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    if (!id) return;
    let active = true;
    void Promise.all([listingsApi.read(id), listingsApi.policies()])
      .then(([data, policyData]) => {
        if (active) {
          setListing(data.listing);
          setForm(toForm(data.listing));
          setPolicies(policyData.items);
          setError("");
          setSaved("All changes saved");
        }
      })
      .catch((e) => {
        if (active)
          setError(
            e instanceof Error ? e.message : "Could not open this listing.",
          );
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);
  useEffect(() => {
    function leave(event: BeforeUnloadEvent) {
      if (
        form &&
        listing &&
        (JSON.stringify(form) !== JSON.stringify(toForm(listing)) || photoBusy)
      ) {
        event.preventDefault();
      }
    }
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [form, listing, photoBusy]);
  function fail(e: unknown) {
    if (e instanceof ApiError) {
      setErrors(e.details.field_errors ?? {});
      if (e.status === 409 && e.details.code === "stale_version")
        setStale(true);
      if (e.status === 401) setExpired(true);
    }
    setError(e instanceof Error ? e.message : "Could not save your listing.");
    setSaved("Changes not saved");
  }
  function lock(value: boolean) {
    busyRef.current = value;
    setBusy(value);
  }
  function update(key: keyof DraftFields, value: string) {
    if (busyRef.current) return;
    setForm((current) => (current ? { ...current, [key]: value } : current));
    setSaved("Unsaved changes");
    setErrors((current) => ({ ...current, [key]: "" }));
  }
  async function save(): Promise<Listing | null> {
    if (!listing || !form || busyRef.current || photoBusy || stale) return null;
    lock(true);
    setError("");
    setErrors({});
    setSaved("Saving…");
    try {
      const changes = changedFields(form, listing);
      const updated = Object.keys(changes).length
        ? (await listingsApi.save(listing.id, listing.version, changes)).listing
        : listing;
      setListing(updated);
      setForm(toForm(updated));
      setSaved("All changes saved");
      return updated;
    } catch (e) {
      fail(e);
      return null;
    } finally {
      lock(false);
    }
  }
  async function advance(next: number) {
    const result = await save();
    if (result) setStep(next);
  }
  async function publish() {
    const updated = await save();
    if (!updated) return;
    lock(true);
    setError("");
    try {
      const result = await listingsApi.publish(updated.id, updated.version);
      setListing(result.listing);
      setForm(toForm(result.listing));
      setSaved("Published successfully");
    } catch (e) {
      fail(e);
    } finally {
      lock(false);
    }
  }
  async function unlist() {
    if (!listing || busyRef.current || photoBusy) return;
    const updated = await save();
    if (!updated) return;
    lock(true);
    try {
      const data = await listingsApi.unlist(updated.id, updated.version);
      setListing(data.listing);
      setForm(toForm(data.listing));
      setSaved("Listing unlisted. Your details and photos are saved.");
    } catch (e) {
      fail(e);
    } finally {
      lock(false);
    }
  }
  async function loadLatest() {
    if (!listing) return;
    lock(true);
    try {
      setLatest((await listingsApi.read(listing.id)).listing);
    } catch (e) {
      fail(e);
    } finally {
      lock(false);
    }
  }
  function rebase() {
    if (!latest || !listing || !form) return;
    const prior = toForm(listing);
    const merged = { ...toForm(latest) };
    for (const key of Object.keys(form) as (keyof DraftFields)[])
      if (form[key] !== prior[key]) merged[key] = form[key];
    // Address and its pin are one unit during conflict recovery.
    const addressEdited = form.address !== prior.address;
    const pinEdited =
      form.latitude !== prior.latitude || form.longitude !== prior.longitude;
    const addressChangedElsewhere = latest.address !== listing.address;
    if (addressEdited) {
      merged.address = form.address;
      merged.latitude = form.latitude;
      merged.longitude = form.longitude;
    } else if (pinEdited && addressChangedElsewhere) {
      // Keep the newer saved address; an old-address adjustment needs reconfirmation.
      merged.latitude = "";
      merged.longitude = "";
    } else if (pinEdited) {
      merged.latitude = form.latitude;
      merged.longitude = form.longitude;
    }
    setForm(merged);
    setListing(latest);
    setLatest(null);
    setStale(false);
    setError("");
    setSaved(
      pinEdited && !addressEdited && addressChangedElsewhere
        ? "The saved address changed elsewhere. Your other edits are kept; confirm a pin for the new address before saving."
        : "Your edits are ready to save against the latest version.",
    );
  }
  async function authenticate() {
    setReauthError("");
    lock(true);
    try {
      await login(reauthEmail, reauthPassword);
      setReauthPassword("");
      setExpired(false);
    } catch (e) {
      setReauthError(e instanceof Error ? e.message : "Could not sign in.");
    } finally {
      lock(false);
    }
  }
  if (expired || (!session.user && originalUser))
    return (
      <main className="host-content">
        <section className="card reauth-panel">
          <h1>Sign in to continue editing</h1>
          <p>
            Your unsaved work is kept in this tab. Sign in with the same
            account, then save again.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void authenticate();
            }}
          >
            <label>
              Email address
              <input
                type="email"
                required
                autoComplete="email"
                value={reauthEmail}
                onChange={(e) => setReauthEmail(e.target.value)}
              />
            </label>
            <label>
              Password
              <input
                type="password"
                required
                autoComplete="current-password"
                value={reauthPassword}
                onChange={(e) => setReauthPassword(e.target.value)}
              />
            </label>
            {reauthError && <ErrorState message={reauthError} />}
            <Button disabled={busy}>Sign in and recover edits</Button>
          </form>
        </section>
      </main>
    );
  if (originalUser && session.user && session.user.id !== originalUser)
    return (
      <main className="host-content">
        <h1>Different account signed in</h1>
        <p>
          These edits belong to another account. Return to your own listings to
          continue.
        </p>
        <Link className="button secondary" to="/host/listings">
          Your listings
        </Link>
      </main>
    );
  if (!listing || !form)
    return (
      <main className="host-content">
        {error ? (
          <ErrorState
            message={error}
            retry={() => {
              setError("");
              setAttempt(attempt + 1);
            }}
          />
        ) : (
          <p role="status">Opening your draft…</p>
        )}
      </main>
    );
  const disabled = busy || photoBusy || stale;
  const field = (
    key: keyof DraftFields,
    label: string,
    options?: {
      type?: string;
      hint?: string;
      choices?: { value: string; label: string }[];
      large?: boolean;
      min?: number;
      max?: number;
      maxLength?: number;
    },
  ) => {
    const props = {
      id: key,
      name: key,
      value: form[key],
      disabled: busy || photoBusy,
      onChange: (
        event: ChangeEvent<
          HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
        >,
      ) => update(key, event.target.value),
      "aria-invalid": !!errors[key],
      "aria-describedby": `${key}-help ${key}-error`,
    };
    return (
      <div
        className={`listing-field ${options?.large ? "full-width" : ""}`}
        key={key}
      >
        <label htmlFor={key}>{label}</label>
        {options?.choices ? (
          <select {...props}>
            <option value="">Select…</option>
            {options.choices.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        ) : options?.large ? (
          <textarea
            {...props}
            rows={key === "description" ? 5 : 3}
            maxLength={options.maxLength}
          />
        ) : (
          <input
            {...props}
            type={options?.type ?? "text"}
            min={options?.min}
            max={options?.max}
            maxLength={options?.maxLength}
            step={options?.type === "number" ? 1 : undefined}
            inputMode={key.includes("_minor") ? "decimal" : undefined}
          />
        )}
        <span id={`${key}-help`} className="field-help">
          {options?.hint ?? ""}
        </span>
        <span id={`${key}-error`} className="field-error">
          {fieldText(errors[key])}
        </span>
      </div>
    );
  };
  let content: ReactNode;
  if (step === 0)
    content = (
      <>
        <h2>Tell us about your place</h2>
        <p className="muted">
          Save what you know now. You can finish the rest later.
        </p>
        <div className="listing-form-grid">
          {field("property_type", "Property type", {
            choices: [
              { value: "apartment", label: "Entire apartment" },
              { value: "house", label: "Entire house" },
              { value: "room", label: "Private room" },
            ],
          })}
          {field("destination", "Destination", {
            hint: "City and country",
            maxLength: 100,
          })}
          <LocationEditor
            key={`${listing.id}-${listing.version}`}
            address={form.address}
            latitude={form.latitude}
            longitude={form.longitude}
            disabled={disabled}
            error={[
              fieldText(errors.address),
              fieldText(errors.latitude),
              fieldText(errors.longitude),
            ]
              .filter(Boolean)
              .join(" ")}
            onChange={(fields) => {
              if (busyRef.current) return;
              setForm((current) =>
                current ? { ...current, ...fields } : current,
              );
              setSaved("Unsaved changes");
              setErrors((current) => ({
                ...current,
                address: "",
                latitude: "",
                longitude: "",
              }));
            }}
          />
          <TimezonePicker
            value={form.timezone}
            onChange={(value) => update("timezone", value)}
            disabled={disabled}
            error={fieldText(errors.timezone)}
          />
          {field("capacity", "Guests", { type: "number", min: 1, max: 30 })}
          {field("bedrooms", "Bedrooms", { type: "number", min: 0, max: 20 })}
          {field("beds", "Beds", { type: "number", min: 1, max: 30 })}
          {field("baths", "Bathrooms", { type: "number", min: 1, max: 20 })}
          <fieldset
            className="listing-field full-width"
            disabled={disabled}
            aria-describedby="categories-help categories-error"
          >
            <legend>Stay categories (optional)</legend>
            <p id="categories-help" className="field-help">
              Choose only categories that accurately describe your place. All
              listings appear under Homes, including places with no categories.
            </p>
            <div className="listing-category-options">
              {STAY_CATEGORIES.filter((category) => category.value).map(
                (category) => (
                  <label
                    key={category.value}
                    className="listing-category-option"
                  >
                    <input
                      id={`categories-${category.value}`}
                      type="checkbox"
                      checked={form.categories
                        .split("\n")
                        .includes(category.value)}
                      onChange={(event) => {
                        const selected = form.categories
                          .split("\n")
                          .filter(Boolean);
                        update(
                          "categories",
                          (event.target.checked
                            ? [...selected, category.value]
                            : selected.filter(
                                (value) => value !== category.value,
                              )
                          ).join("\n"),
                        );
                      }}
                    />
                    {category.label}
                  </label>
                ),
              )}
            </div>
            <span id="categories-error" className="field-error">
              {fieldText(errors.categories)}
            </span>
          </fieldset>
        </div>
      </>
    );
  else if (step === 1)
    content = (
      <>
        <PhotoManager
          listing={listing}
          disabled={busy || stale}
          onBusy={setPhotoBusy}
          onChange={(updated) => {
            const prior = toForm(photoBaseline.current ?? listing);
            photoBaseline.current = updated;
            setForm((current) => {
              if (!current) return current;
              const merged = { ...toForm(updated) };
              for (const key of Object.keys(current) as (keyof DraftFields)[])
                if (current[key] !== prior[key]) merged[key] = current[key];
              return merged;
            });
            setListing(updated);
            setSaved("Photos saved · save any content edits before leaving");
          }}
        />
        {errors.photos && (
          <p className="field-error">{fieldText(errors.photos)}</p>
        )}
        <div className="listing-form-grid">
          {field("title", "Listing title", { maxLength: 100 })}
          {field("description", "Description", {
            large: true,
            maxLength: 5000,
          })}
          {field("amenities", "Amenities", {
            large: true,
            hint: "One amenity per line, up to 30. Examples: Wifi, Kitchen, Air conditioning.",
          })}
        </div>
      </>
    );
  else if (step === 2)
    content = (
      <>
        <h2>Set your price and house rules</h2>
        <p className="muted">
          All amounts are in EUR. Set terms for future stays.
        </p>
        <div className="listing-form-grid">
          {field("nightly_minor", "Nightly price (EUR)", {
            hint: "At least €1.00. Use up to two decimal places.",
          })}
          {field("cleaning_minor", "Cleaning fee (EUR)", {
            hint: "Enter 0 for no cleaning fee.",
          })}
          {field("policy_id", "Cancellation policy", {
            hint: "Changes apply to future bookings. Existing reservations keep their booked policy and version.",
            choices: policies.map((policy) => ({
              value: policy.id,
              label: `${policy.name} · v${policy.version}`,
            })),
          })}
          <section
            className="policy-comparison full-width"
            aria-labelledby="policy-comparison-heading"
          >
            <h3 id="policy-comparison-heading">
              Compare cancellation policies
            </h3>
            {policies.find((policy) => policy.id === form.policy_id) && (
              <div className="selected-policy-summary" role="status">
                <strong>
                  Selected:{" "}
                  {
                    policies.find((policy) => policy.id === form.policy_id)
                      ?.name
                  }
                </strong>
                <p>
                  {policies.find((policy) => policy.id === form.policy_id)
                    ?.terms ??
                    "Policy terms could not load. Reload before choosing a policy."}
                </p>
              </div>
            )}
            <dl>
              {policies.map((policy) => (
                <div key={policy.id}>
                  <dt>
                    {policy.name} · v{policy.version}
                  </dt>
                  <dd>
                    {policy.terms ??
                      "Policy terms unavailable. Reload this draft to retry."}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
          {field("booking_mode", "Booking mode", {
            choices: [
              { value: "instant", label: "Instant booking" },
              { value: "request", label: "Request to book" },
            ],
          })}
          {field("check_in_time", "Check-in time", { type: "time" })}
          {field("check_out_time", "Check-out time", { type: "time" })}
          {field("house_rules", "House rules", {
            large: true,
            hint: "One rule per line. Be welcoming and fair; discriminatory restrictions are not allowed.",
          })}
        </div>
        <p className="muted moderation-note">
          Publication includes basic automated checks. These demo checks are not
          comprehensive moderation.
        </p>
      </>
    );
  else
    content = (
      <>
        <h2>Ready when you are</h2>
        <p className="muted">
          Review your details, then publish. You need all required fields and at
          least five verified photos.
        </p>
        <div className="review-summary">
          <h3>{form.title || "Untitled listing"}</h3>
          <p>
            {form.destination || "Destination not set"} ·{" "}
            {form.property_type || "Type not set"}
          </p>
          <dl>
            <div>
              <dt>Photos</dt>
              <dd>{listing.photos.length} verified</dd>
            </div>
            <div>
              <dt>Guests</dt>
              <dd>{form.capacity || "Not set"}</dd>
            </div>
            <div>
              <dt>Nightly price</dt>
              <dd>
                {form.nightly_minor ? `€${form.nightly_minor}` : "Not set"}
              </dd>
            </div>
            <div>
              <dt>Booking mode</dt>
              <dd>{form.booking_mode || "Not set"}</dd>
            </div>
          </dl>
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() =>
              void save().then((result) => {
                if (result) navigate(`/host/listings/${listing.id}/preview`);
              })
            }
          >
            Save and preview
          </Button>
        </div>
        <p className="muted">
          Publishing makes this listing ready for future guest discovery. Search
          and booking are not part of this milestone.
        </p>
        {listing.status !== "published" && (
          <Button disabled={disabled} onClick={() => void publish()}>
            {busy ? "Publishing…" : "Publish listing"}
          </Button>
        )}
        {listing.status === "published" && (
          <div className="publication-success" role="status">
            <strong>Your listing is published.</strong>
            <p>Details and photos have passed the required checks.</p>
            <Link
              className="button secondary"
              to={`/host/listings/${listing.id}/preview`}
            >
              Preview listing
            </Link>
          </div>
        )}
      </>
    );
  return (
    <main className="host-content listing-wizard">
      <div className="wizard-heading">
        <div>
          <div className="breadcrumbs">
            <Link to="/host/listings">Listings</Link> /{" "}
            {listing.title ?? "New listing"}
          </div>
          <h1>
            {listing.status === "draft"
              ? "Create your listing"
              : "Edit your listing"}
          </h1>
          <div className="save-status">
            <StatusBadge status={listing.status} />
            <span role="status">{saved}</span>
          </div>
        </div>
        <div className="wizard-top-actions">
          {listing.status === "published" && (
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => void unlist()}
            >
              Unlist
            </Button>
          )}
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() =>
              void save().then((result) => {
                if (result) navigate("/host/listings");
              })
            }
          >
            Save and exit
          </Button>
        </div>
      </div>
      <ol className="wizard-steps">
        {steps.map((name, index) => (
          <li key={name}>
            <button
              type="button"
              disabled={disabled}
              aria-current={index === step ? "step" : undefined}
              onClick={() => void advance(index)}
            >
              <span>{index + 1}</span>
              {name}
            </button>
          </li>
        ))}
      </ol>
      {error && <ErrorState message={error} />}{" "}
      {!!Object.values(errors).filter(Boolean).length && (
        <div className="publication-errors" role="alert">
          <strong>Please check these fields</strong>
          <ul>
            {Object.entries(errors)
              .filter(([, value]) => value)
              .map(([key, value]) => (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => {
                      setStep(
                        [
                          "property_type",
                          "address",
                          "destination",
                          "timezone",
                          "capacity",
                          "bedrooms",
                          "beds",
                          "baths",
                          "categories",
                        ].includes(key)
                          ? 0
                          : [
                                "photos",
                                "title",
                                "description",
                                "amenities",
                              ].includes(key)
                            ? 1
                            : 2,
                      );
                      setTimeout(
                        () =>
                          (key === "categories"
                            ? document.querySelector<HTMLInputElement>(
                                'input[id^="categories-"]',
                              )
                            : document.getElementById(key)
                          )?.focus(),
                        0,
                      );
                    }}
                  >
                    {key.replaceAll("_", " ")}: {fieldText(value)}
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
      {stale && (
        <div className="stale-recovery">
          <p>
            Your draft changed in another tab. Your entered values are still
            here. Load the latest saved version before deciding how to continue.
          </p>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => void loadLatest()}
          >
            Load latest saved version
          </Button>
          {latest && (
            <>
              <p>
                Latest version {latest.version}:{" "}
                {latest.title ?? "Untitled listing"} · {latest.status}. Keeping
                your edits will apply only the fields you changed on top of this
                version.
              </p>
              <Button onClick={rebase}>Keep my edits on latest version</Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setListing(latest);
                  setForm(toForm(latest));
                  setLatest(null);
                  setStale(false);
                  setError("");
                  setSaved("Latest saved version loaded");
                }}
              >
                Discard my edits and reload
              </Button>
            </>
          )}
        </div>
      )}
      <section className="wizard-panel" aria-busy={busy || photoBusy}>
        {content}
      </section>
      <footer className="wizard-footer">
        <Button
          variant="secondary"
          disabled={disabled || step === 0}
          onClick={() => void advance(step - 1)}
        >
          Back
        </Button>
        <Button
          variant="secondary"
          disabled={disabled}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save draft"}
        </Button>
        {step < 3 && (
          <Button disabled={disabled} onClick={() => void advance(step + 1)}>
            Save and continue
          </Button>
        )}
      </footer>
    </main>
  );
}
