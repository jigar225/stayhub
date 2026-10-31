import { Fragment, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useBusinessTime } from "../api/businessTime";
import { DateRangePicker } from "./DateRangePicker";
import { StayIcon } from "./StayIcon";
import { Button } from "../components/ui";
import {
  earliestCheckIn,
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
  preserveQuery = "",
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
  preserveQuery?: string;
  onSubmit?: (values: SearchValues) => void;
  busy?: boolean;
  requireDates?: boolean;
  onDirty?: (values: SearchValues) => void;
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
      const query = new URLSearchParams(preserveQuery);
      for (const key of [
        "destination",
        "check_in",
        "check_out",
        "guests",
        "cursor",
      ])
        query.delete(key);
      new URLSearchParams(searchQuery(values)).forEach((value, key) =>
        query.set(key, value),
      );
      if (category && !query.has("category")) query.set("category", category);
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
          { key: "guests", label: joined ? "Who" : "Guests", type: "number" },
        ] as const
      ).map((field) => (
        <Fragment key={field.key}>
          {field.key === "guests" && (
            <DateRangePicker
              checkIn={values.check_in}
              checkOut={values.check_out}
              minimum={minimum}
              disabled={busy}
              requireDates={requireDates}
              errors={displayedErrors}
              onApply={(range) => {
                if (
                  range.check_in !== values.check_in ||
                  range.check_out !== values.check_out
                )
                  onDirty?.({ ...values, ...range });
                setValues((current) => ({ ...current, ...range }));
                setErrors((current) => ({
                  ...current,
                  check_in: "",
                  check_out: "",
                }));
              }}
            />
          )}
          <div className={`search-field search-${field.key}`}>
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
                    const value = event.target.value;
                    onDirty?.({ ...values, [field.key]: value });
                    setValues({ ...values, [field.key]: value });
                    setErrors({ ...errors, [field.key]: "" });
                  }}
                  min={field.key === "guests" ? 1 : undefined}
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
                  <span
                    className="field-error"
                    id={`search-${field.key}-error`}
                  >
                    {displayedErrors[field.key]}
                  </span>
                )}
              </>
            )}
          </div>
        </Fragment>
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
