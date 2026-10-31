import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Button } from "../components/ui";
import {
  AMENITIES,
  emptyFilters,
  readFilters,
  validateFilters,
  type FilterDraft,
} from "./filters";

export function FiltersDrawer({
  params,
  onApply,
  onClose,
}: {
  params: URLSearchParams;
  onApply: (draft: FilterDraft) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState(() => readFilters(params));
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    const node = dialog.current;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    node?.showModal();
    return () => {
      node?.close();
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, []);
  function update<K extends keyof FilterDraft>(key: K, value: FilterDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: "" }));
  }
  function trapTab(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const node = event.currentTarget;
    const available = Array.from(
      node.querySelectorAll<HTMLElement>(
        'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex]',
      ),
    ).filter((element) => {
      const style = getComputedStyle(element);
      return (
        element.tabIndex >= 0 &&
        !element.matches(":disabled") &&
        !element.closest("[hidden], [inert]") &&
        style.display !== "none" &&
        style.visibility !== "hidden"
      );
    });
    // Native radio groups contribute one tab stop; leave their arrow-key
    // behavior and every interior Tab movement to the browser.
    const stops = available.filter((element) => {
      if (
        !(element instanceof HTMLInputElement) ||
        element.type !== "radio" ||
        !element.name
      )
        return true;
      const group = available.filter(
        (peer): peer is HTMLInputElement =>
          peer instanceof HTMLInputElement &&
          peer.type === "radio" &&
          peer.name === element.name,
      );
      return element === (group.find((peer) => peer.checked) ?? group[0]);
    });
    const first = stops[0],
      last = stops.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const next = validateFilters(draft);
    setErrors(next);
    if (Object.keys(next).length) {
      dialog.current
        ?.querySelector<HTMLElement>(`[name="${Object.keys(next)[0]}"]`)
        ?.focus();
      return;
    }
    onApply(draft);
  }
  return (
    <dialog
      ref={dialog}
      className="filters-drawer"
      aria-labelledby="filters-title"
      onKeyDown={trapTab}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          onClose();
      }}
    >
      <form onSubmit={submit} noValidate>
        <header className="filters-heading">
          <h2 id="filters-title">Filters</h2>
          <Button
            type="button"
            variant="ghost"
            aria-label="Close filters"
            onClick={onClose}
          >
            ×
          </Button>
        </header>
        <div className="filters-body">
          <fieldset className="filter-section">
            <legend>Type of place</legend>
            <div className="filter-place-options">
              {[
                ["", "Any type"],
                ["entire", "Entire place"],
                ["private", "Private room"],
              ].map(([value, label]) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="place"
                    value={value}
                    checked={draft.place === value}
                    onChange={() => update("place", value)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            {errors.place && (
              <p className="field-error" role="alert">
                {errors.place}
              </p>
            )}
          </fieldset>
          <fieldset className="filter-section">
            <legend>Price range</legend>
            <p className="muted">
              Nightly price in EUR, before cleaning and service fees.
            </p>
            <div className="filter-price-range">
              {[
                ["minimum", "Minimum"],
                ["maximum", "Maximum"],
              ].map(([key, label]) => (
                <label key={key} htmlFor={`filter-${key}`}>
                  <span id={`filter-${key}-label`}>{label}</span>
                  <div className="filter-money">
                    <span aria-hidden="true">€</span>
                    <input
                      id={`filter-${key}`}
                      name={key}
                      aria-labelledby={`filter-${key}-label`}
                      inputMode="decimal"
                      value={draft[key as "minimum" | "maximum"]}
                      onChange={(event) =>
                        update(key as "minimum" | "maximum", event.target.value)
                      }
                      placeholder="Any"
                      maxLength={9}
                      aria-invalid={!!errors[key]}
                      aria-describedby={
                        errors[key] ? `filter-${key}-error` : undefined
                      }
                    />
                  </div>
                  {errors[key] && (
                    <span
                      id={`filter-${key}-error`}
                      className="field-error"
                      role="alert"
                    >
                      {errors[key]}
                    </span>
                  )}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="filter-section">
            <legend>Rooms and beds</legend>
            {(
              [
                ["bedrooms", "Minimum bedrooms", 20],
                ["beds", "Minimum beds", 30],
              ] as const
            ).map(([key, label, maximum]) => {
              const count = Number(draft[key]);
              const valid = /^\d+$/.test(draft[key]) && count <= maximum;
              return (
                <div className="filter-count-row" key={key}>
                  <span id={`filter-${key}-label`}>{label}</span>
                  <div
                    className="filter-count-stepper"
                    role="group"
                    aria-labelledby={`filter-${key}-label`}
                  >
                    <Button
                      type="button"
                      variant="ghost"
                      className="filter-count-step"
                      name={key}
                      aria-label={`Decrease ${label.toLowerCase()}`}
                      aria-describedby={
                        errors[key] ? `filter-${key}-error` : undefined
                      }
                      disabled={valid && count === 0}
                      onClick={() =>
                        update(
                          key,
                          String(Math.max(0, (valid ? count : 0) - 1)),
                        )
                      }
                    >
                      <span aria-hidden="true">−</span>
                    </Button>
                    <output
                      className="filter-count-value"
                      aria-label={`${label} value`}
                      aria-live="polite"
                    >
                      {valid ? (count ? `${count}+` : "Any") : "Not set"}
                    </output>
                    <Button
                      type="button"
                      variant="ghost"
                      className="filter-count-step"
                      aria-label={`Increase ${label.toLowerCase()}`}
                      disabled={valid && count === maximum}
                      onClick={() =>
                        update(
                          key,
                          String(Math.min(maximum, (valid ? count : 0) + 1)),
                        )
                      }
                    >
                      <span aria-hidden="true">+</span>
                    </Button>
                  </div>
                  {errors[key] && (
                    <p
                      id={`filter-${key}-error`}
                      className="field-error"
                      role="alert"
                    >
                      {errors[key]}
                    </p>
                  )}
                </div>
              );
            })}
          </fieldset>
          <fieldset className="filter-section">
            <legend>Amenities</legend>
            <p className="muted">
              Your stay must include every selected amenity.
            </p>
            <div className="filter-amenities">
              {AMENITIES.map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    name="amenities"
                    checked={draft.amenities.includes(key)}
                    onChange={(event) =>
                      update(
                        "amenities",
                        event.target.checked
                          ? [...draft.amenities, key]
                          : draft.amenities.filter((value) => value !== key),
                      )
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            {errors.amenities && (
              <p className="field-error" role="alert">
                {errors.amenities}
              </p>
            )}
          </fieldset>
          <fieldset className="filter-section">
            <legend>Booking options</legend>
            <label className="filter-instant">
              <span>
                <strong>Instant book</strong>
                <span className="muted">
                  Book without waiting for host approval.
                </span>
              </span>
              <input
                type="checkbox"
                name="instant"
                checked={draft.instant}
                onChange={(event) => update("instant", event.target.checked)}
              />
            </label>
          </fieldset>
        </div>
        <footer className="filters-footer">
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft(emptyFilters());
              setErrors({});
            }}
          >
            Clear all
          </Button>
          <Button type="submit">Show stays</Button>
        </footer>
      </form>
    </dialog>
  );
}
