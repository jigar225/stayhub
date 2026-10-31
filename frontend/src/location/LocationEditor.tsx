import { useEffect, useId, useRef, useState } from "react";
import { locationApi, type Point, type Suggestion } from "./api";
import "./location.css";
import { MapPanel } from "./MapPanel";

function parsePoint(latitude: string, longitude: string): Point | null {
  if (!latitude.trim() || !longitude.trim()) return null;
  const lat = Number(latitude),
    lon = Number(longitude);
  return Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180
    ? { latitude: lat, longitude: lon }
    : null;
}

export function LocationEditor({
  address,
  latitude,
  longitude,
  disabled,
  error,
  onChange,
}: {
  address: string;
  latitude: string;
  longitude: string;
  disabled: boolean;
  error?: string;
  onChange: (fields: {
    address: string;
    latitude: string;
    longitude: string;
  }) => void;
}) {
  const id = useId();
  const [search, setSearch] = useState<{
    query: string;
    generation: number;
  } | null>(null);
  const [results, setResults] = useState<{
    generation: number;
    items: Suggestion[];
    error: string;
  } | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const generation = useRef(0);
  const [manual, setManual] = useState<{
    latitude: string;
    longitude: string;
  } | null>(null);
  const confirmed = parsePoint(latitude, longitude);
  const manualLat = manual?.latitude ?? latitude;
  const manualLon = manual?.longitude ?? longitude;
  const point = manual
    ? parsePoint(manual.latitude, manual.longitude)
    : confirmed;
  const items =
    results?.generation === search?.generation ? (results?.items ?? []) : [];
  const loading = !!search && results?.generation !== search.generation;
  const searchError =
    results?.generation === search?.generation ? results?.error : "";
  useEffect(() => {
    if (!search || search.query.trim().length < 3 || disabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void locationApi
        .autocomplete(search.query.trim(), controller.signal)
        .then((data) => {
          if (
            generation.current === search.generation &&
            !controller.signal.aborted
          )
            setResults({
              generation: search.generation,
              items: data.items,
              error: "",
            });
        })
        .catch((e) => {
          if (
            generation.current === search.generation &&
            !controller.signal.aborted
          )
            setResults({
              generation: search.generation,
              items: [],
              error:
                e instanceof Error
                  ? e.message
                  : "Address suggestions unavailable. Enter an address and set a pin manually.",
            });
        });
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [search, disabled]);
  function select(suggestion: Suggestion) {
    generation.current++;
    setSearch(null);
    setOpen(false);
    setActive(-1);
    setManual(null);
    const unit = address.match(
      /(?:,\s*)?((?:apt\.?|apartment|unit|suite|flat|#)\s*[\w-]+)\s*$/i,
    )?.[1];
    onChange({
      address: `${suggestion.display_address}${unit ? `, ${unit}` : ""}`.slice(
        0,
        300,
      ),
      latitude: String(suggestion.latitude),
      longitude: String(suggestion.longitude),
    });
  }
  function move(next: Point) {
    if (disabled) return;
    setManual(null);
    onChange({
      address,
      latitude: next.latitude.toFixed(6),
      longitude: next.longitude.toFixed(6),
    });
  }
  function editCoordinate(key: "latitude" | "longitude", value: string) {
    const next = { latitude: manualLat, longitude: manualLon, [key]: value };
    setManual(next);
    onChange({ address, latitude: "", longitude: "" });
  }
  return (
    <div className="location-editor listing-field full-width">
      <div className="location-address-field">
        <label htmlFor="address">Street address</label>
        <input
          id="address"
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open && !!search}
          aria-controls={`${id}-options`}
          aria-activedescendant={
            open && active >= 0 && items[active]
              ? `${id}-option-${active}`
              : undefined
          }
          aria-describedby={`${id}-help ${id}-status address-error`}
          aria-invalid={!!error}
          value={address}
          disabled={disabled}
          maxLength={300}
          onChange={(event) => {
            const value = event.target.value;
            const nextGeneration = ++generation.current;
            onChange({ address: value, latitude: "", longitude: "" });
            setManual(null);
            setActive(-1);
            setOpen(true);
            setSearch(
              value.trim().length >= 3
                ? { query: value, generation: nextGeneration }
                : null,
            );
          }}
          onBlur={(event) => {
            if (
              !event.currentTarget.parentElement?.contains(event.relatedTarget)
            )
              setOpen(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              setActive(-1);
            } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActive((prior) =>
                items.length
                  ? (prior +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      items.length) %
                    items.length
                  : -1,
              );
            } else if (
              event.key === "Enter" &&
              open &&
              active >= 0 &&
              items[active]
            ) {
              event.preventDefault();
              select(items[active]);
            }
          }}
        />
        {open && search && (
          <div className="location-suggestions">
            <ul
              id={`${id}-options`}
              role="listbox"
              aria-label="Address suggestions"
            >
              {items.map((item, index) => (
                <li
                  key={`${index}-${item.display_address}`}
                  id={`${id}-option-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => select(item)}
                >
                  {item.display_address}
                </li>
              ))}
            </ul>
            <p aria-live="polite">
              {loading
                ? "Looking for addresses…"
                : searchError ||
                  (!items.length
                    ? "No matching addresses. Enter your address and set the pin manually."
                    : "Use arrow keys and Enter to choose an address.")}
            </p>
          </div>
        )}
      </div>
      <p className="field-help" id={`${id}-help`}>
        Address suggestions powered by{" "}
        <a href="https://www.geoapify.com/" target="_blank" rel="noreferrer">
          Geoapify
        </a>
        . Type at least 3 characters. Apartment or unit details are retained
        when choosing a suggestion. No suggestions? Enter your address and
        confirm coordinates below.
      </p>
      <p className="location-pin-status" id={`${id}-status`} aria-live="polite">
        {confirmed
          ? "Pin selected · precise location visible only to you. Save draft to keep it."
          : "No confirmed pin. Select an address, click the map, or enter and confirm coordinates. Saving now keeps the address without a location."}
      </p>
      <MapPanel point={point} onChange={move} disabled={disabled} />
      <p className="field-help">
        Click the map or drag the pin to correct its position. You can also use
        the coordinate fields. The public map shows only an approximate area;
        this is not an anonymity guarantee.
      </p>
      <div className="location-coordinate-fields">
        <label>
          Latitude
          <input
            aria-label="Latitude"
            type="number"
            inputMode="decimal"
            step="any"
            min={-90}
            max={90}
            value={manualLat}
            disabled={disabled}
            onChange={(event) => editCoordinate("latitude", event.target.value)}
          />
        </label>
        <label>
          Longitude
          <input
            aria-label="Longitude"
            type="number"
            inputMode="decimal"
            step="any"
            min={-180}
            max={180}
            value={manualLon}
            disabled={disabled}
            onChange={(event) =>
              editCoordinate("longitude", event.target.value)
            }
          />
        </label>
        <button
          className="button secondary"
          type="button"
          disabled={disabled || !parsePoint(manualLat, manualLon)}
          onClick={() => {
            const next = parsePoint(manualLat, manualLon);
            if (next) move(next);
          }}
        >
          Confirm pin
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={disabled || (!latitude && !longitude && !manual)}
          onClick={() => {
            setManual(null);
            onChange({ address, latitude: "", longitude: "" });
          }}
        >
          Remove pin
        </button>
      </div>
      <span className="field-error" id="address-error">
        {error}
      </span>
    </div>
  );
}
