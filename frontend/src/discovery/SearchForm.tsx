import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useBusinessTime } from "../api/businessTime";
import { StayIcon } from "./StayIcon";
import { Button } from "../components/ui";
import {
  earliestCheckIn,
  addDays,
  validDate,
  searchQuery,
  validateSearch,
  type SearchValues,
  type StaySchedule,
} from "./dates";
export function SearchForm({
  initial,
  compact = false,
  joined = false,
  category = "",
  onSubmit,
  busy = false,
  requireDates = false,
  onDirty,
  schedule,
}: {
  initial: SearchValues;
  compact?: boolean;
  joined?: boolean;
  category?: string;
  onSubmit?: (values: SearchValues) => void;
  busy?: boolean;
  requireDates?: boolean;
  onDirty?: () => void;
  schedule?: StaySchedule;
}) {
  const navigate = useNavigate();
  const [values, setValues] = useState(initial);
  const clock = useBusinessTime();
  const minimum = clock.now ? earliestCheckIn(schedule, clock.now) : undefined;
  const [errors, setErrors] = useState<Record<string, string>>(() =>
    initial.check_in || initial.check_out
      ? validateSearch(initial, requireDates, minimum)
      : {},
  );
  const displayedErrors: Record<string, string> = {
    ...errors,
    ...(minimum &&
    values.check_in &&
    validDate(values.check_in) &&
    values.check_in < minimum
      ? {
          check_in:
            "Choose a later check-in date for this listing’s local time and booking lead time.",
        }
      : {}),
  };
  function submit(event: FormEvent) {
    event.preventDefault();
    const next = validateSearch(
      values,
      requireDates,
      clock.now ? earliestCheckIn(schedule, clock.now) : undefined,
    );
    setErrors(next);
    if (Object.keys(next).length) {
      document.getElementById(`search-${Object.keys(next)[0]}`)?.focus();
      return;
    }
    if (onSubmit) onSubmit(values);
    else {
      const query = new URLSearchParams(searchQuery(values));
      if (category) query.set("category", category);
      navigate(`/stays?${query}`);
    }
  }
  return (
    <form
      className={`stay-search ${compact ? "compact" : ""} ${joined ? "joined" : ""}`}
      onSubmit={submit}
      noValidate
    >
      {clock.error && (
        <div className="clock-feedback" role="alert">
          <p>{clock.error}</p>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void clock.refresh()}
          >
            Refresh business time
          </Button>
        </div>
      )}
      {(
        [
          {
            key: "destination",
            label: "Where",
            type: "text",
            placeholder: "City or destination",
          },
          { key: "check_in", label: "Check in", type: "date" },
          { key: "check_out", label: "Check out", type: "date" },
          { key: "guests", label: joined ? "Who" : "Guests", type: "number" },
        ] as const
      ).map((field) => (
        <div className={`search-field search-${field.key}`} key={field.key}>
          {field.key === "destination" && compact ? null : (
            <>
              <label htmlFor={`search-${field.key}`}>{field.label}</label>
              <input
                id={`search-${field.key}`}
                name={field.key}
                type={field.type}
                value={values[field.key]}
                placeholder={
                  "placeholder" in field ? field.placeholder : undefined
                }
                onChange={(event) => {
                  onDirty?.();
                  const value = event.target.value;
                  const clearCheckout =
                    field.key === "check_in" &&
                    !!values.check_out &&
                    values.check_out <= value;
                  setValues({
                    ...values,
                    [field.key]: value,
                    ...(clearCheckout ? { check_out: "" } : {}),
                  });
                  setErrors({
                    ...errors,
                    [field.key]: "",
                    ...(clearCheckout
                      ? {
                          check_out:
                            "Check-in changed. Select a new check-out date after check-in.",
                        }
                      : {}),
                  });
                }}
                min={
                  field.key === "guests"
                    ? 1
                    : field.key === "check_in"
                      ? minimum
                      : field.key === "check_out"
                        ? validDate(values.check_in) || minimum
                          ? addDays(
                              validDate(values.check_in) &&
                                (!minimum || values.check_in >= minimum)
                                ? values.check_in
                                : (minimum ?? ""),
                              1,
                            )
                          : undefined
                        : undefined
                }
                max={field.key === "guests" ? 30 : undefined}
                maxLength={field.key === "destination" ? 100 : undefined}
                aria-invalid={!!displayedErrors[field.key]}
                aria-describedby={
                  displayedErrors[field.key]
                    ? `search-${field.key}-error`
                    : undefined
                }
                disabled={busy}
              />
              {displayedErrors[field.key] && (
                <span className="field-error" id={`search-${field.key}-error`}>
                  {displayedErrors[field.key]}
                </span>
              )}
            </>
          )}
        </div>
      ))}
      <Button
        type="submit"
        disabled={busy}
        aria-label={joined ? "Search stays" : undefined}
      >
        {joined ? (
          <StayIcon name="search" />
        ) : busy ? (
          "Checking…"
        ) : compact ? (
          "Check price"
        ) : (
          "Search stays"
        )}
      </Button>
    </form>
  );
}
