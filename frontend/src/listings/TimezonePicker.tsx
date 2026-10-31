import { useEffect, useId, useState } from "react";
import { timezoneApi, type TimezoneOption } from "./api";
import { Button } from "../components/ui";

export function TimezonePicker({
  value,
  onChange,
  disabled,
  error,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
}) {
  const listId = useId();
  const [zones, setZones] = useState<TimezoneOption[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [failure, setFailure] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [suggestion] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  useEffect(() => {
    let current = true;
    void timezoneApi()
      .then((data) => {
        if (current) {
          setZones(data.items);
          setFailure("");
        }
      })
      .catch(() => {
        if (current)
          setFailure(
            "Timezone choices could not load. Your saved timezone is preserved; retry to search choices.",
          );
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [attempt]);
  const search = value.toLowerCase().replaceAll("_", " ");
  const choices = zones
    .filter((zone) =>
      zone.label.toLowerCase().replaceAll("_", " ").includes(search),
    )
    .slice(0, 40);
  const choose = (zone: string) => {
    onChange(zone);
    setOpen(false);
    setActive(-1);
  };
  useEffect(() => {
    if (open && active >= 0)
      document
        .getElementById(`${listId}-${active}`)
        ?.scrollIntoView?.({ block: "nearest" });
  }, [active, open, listId]);
  return (
    <div className="listing-field timezone-picker">
      <label htmlFor="timezone">Timezone</label>
      <input
        id="timezone"
        name="timezone"
        maxLength={100}
        role="combobox"
        autoComplete="off"
        value={value}
        disabled={disabled}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          open && active >= 0 && choices[active]
            ? `${listId}-${active}`
            : undefined
        }
        aria-invalid={!!error}
        aria-describedby="timezone-help timezone-error"
        onFocus={() => {
          setOpen(true);
          setActive(-1);
        }}
        onBlur={() => setOpen(false)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
            setActive(-1);
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setActive((index) =>
              choices.length
                ? index < 0
                  ? event.key === "ArrowDown"
                    ? 0
                    : choices.length - 1
                  : (index +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      choices.length) %
                    choices.length
                : -1,
            );
          } else if (
            event.key === "Enter" &&
            open &&
            active >= 0 &&
            choices[active]
          ) {
            event.preventDefault();
            choose(choices[active].value);
          }
        }}
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Supported property timezones"
          className="timezone-options"
        >
          {choices.map((zone, index) => (
            <li
              role="option"
              id={`${listId}-${index}`}
              key={zone.value}
              aria-selected={index === active}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(zone.value)}
            >
              {zone.label}
            </li>
          ))}
          {!choices.length && (
            <li role="presentation">
              {loading
                ? "Loading timezones…"
                : "No matching timezone. Search a region or city."}
            </li>
          )}
        </ul>
      )}
      <span id="timezone-help" className="field-help">
        Search a region or city, such as Asia/Kolkata. This controls
        property-local check-in and check-out. Seasonal daylight-saving changes
        follow the selected timezone.
      </span>
      {suggestion && suggestion !== value && (
        <Button
          variant="secondary"
          disabled={
            disabled || !zones.some((zone) => zone.value === suggestion)
          }
          onClick={() => choose(suggestion)}
        >
          Use browser suggestion: {suggestion}
        </Button>
      )}
      <span id="timezone-error" className="field-error">
        {error}
      </span>
      {failure && (
        <div role="status">
          <p>{failure}</p>
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => {
              setLoading(true);
              setAttempt(attempt + 1);
            }}
          >
            Retry timezone choices
          </Button>
        </div>
      )}
    </div>
  );
}
