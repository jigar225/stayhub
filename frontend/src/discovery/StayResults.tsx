import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, EmptyState, ErrorState } from "../components/ui";
import { ApiError } from "../api/client";
import { discoveryApi, type PublicSummary } from "./api";
import { SearchForm } from "./SearchForm";
import { searchValues } from "./dates";
import { STAY_CATEGORIES } from "./categories";
import { StayIcon } from "./StayIcon";
import { PublicPhotos } from "./PublicPhotos";
import { FiltersDrawer } from "./FiltersDrawer";
import { activeFilterCount, applyFilters } from "./filters";
import { formatEUR } from "../listings/form";
import { ResultsMapPanel } from "./ResultsMapPanel";
import { listingsQuery, boundsQuery, type Bounds } from "./mapSearch";
export function StayResults({ explore = false }: { explore?: boolean }) {
  const [params, setParams] = useSearchParams();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const generation = useRef(0);
  const moreRequest = useRef<{
    generation: number;
    controller: AbortController;
  } | null>(null);
  const category = params.get("category") ?? "";
  const query = params.toString();
  const mapView = !explore && params.get("view") === "map";
  const autoSearch = params.get("move") === "true";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftBounds, setDraftBounds] = useState<Bounds | null>(null);
  const bounds = useMemo(() => {
    if (!["west", "south", "east", "north"].every((key) => params.has(key)))
      return null;
    const point = Object.fromEntries(
      ["west", "south", "east", "north"].map((key) => [
        key,
        Number(params.get(key)),
      ]),
    ) as Bounds;
    return Object.values(point).every(Number.isFinite) &&
      point.south < point.north &&
      point.west !== point.east &&
      Math.abs(point.south) <= 90 &&
      Math.abs(point.north) <= 90 &&
      Math.abs(point.west) <= 180 &&
      Math.abs(point.east) <= 180
      ? point
      : null;
  }, [params]);
  function switchView(view: string) {
    const next = new URLSearchParams(params);
    next.set("view", view);
    next.delete("cursor");
    setParams(next);
  }
  const searchArea = useCallback(
    (area: Bounds, replace = false) => {
      const next = new URLSearchParams(query);
      next.set("view", "map");
      next.delete("cursor");
      for (const [key, value] of Object.entries(boundsQuery(area)))
        next.set(key, value);
      if (next.toString() !== query) setParams(next, { replace });
    },
    [query, setParams],
  );
  const areaSearch = useRef(searchArea);
  const moveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  useEffect(() => {
    areaSearch.current = searchArea;
    clearTimeout(moveTimer.current);
  }, [searchArea]);
  useEffect(() => {
    if (!mapView || !autoSearch || !draftBounds) return;
    moveTimer.current = setTimeout(
      () => areaSearch.current(draftBounds, true),
      400,
    );
    return () => clearTimeout(moveTimer.current);
  }, [mapView, autoSearch, draftBounds]);
  const selected = selectedId;
  const [attempt, setAttempt] = useState(0);
  const requestKey = useMemo(() => ({ query, attempt }), [query, attempt]);
  const [data, setData] = useState<{
    query: string;
    requestKey: object;
    generation: number;
    items: PublicSummary[];
    cursor: string | null;
    truncated: boolean;
  } | null>(null);
  const [failure, setFailure] = useState<{
    query: string;
    requestKey: object;
    message: string;
  } | null>(null);
  const [moreQuery, setMoreQuery] = useState<{
    requestKey: object;
    generation: number;
  } | null>(null);
  const moreBusy =
    moreQuery?.requestKey === requestKey &&
    moreQuery?.generation === data?.generation;
  const [moreError, setMoreError] = useState<{
    query: string;
    generation: number;
    message: string;
  } | null>(null);
  useEffect(() => {
    let active = true;
    const requestGeneration = ++generation.current;
    const controller = new AbortController();
    void discoveryApi
      .search(listingsQuery(new URLSearchParams(query)), controller.signal)
      .then((result) => {
        if (active) {
          setData({
            query,
            requestKey,
            generation: requestGeneration,
            items: result.items,
            cursor: result.next_cursor,
            truncated: result.map_truncated ?? false,
          });
          setFailure(null);
        }
      })
      .catch((error) => {
        if (active)
          setFailure({
            query,
            requestKey,
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
      generation.current += 1;
      moreRequest.current?.controller.abort();
      moreRequest.current = null;
    };
  }, [query, requestKey]);
  const current = data?.requestKey === requestKey ? data : null;
  const error = failure?.requestKey === requestKey ? failure.message : null;
  async function more() {
    if (!current?.cursor || moreRequest.current) return;
    const requestGeneration = current.generation;
    const controller = new AbortController();
    moreRequest.current = { generation: requestGeneration, controller };
    setMoreQuery({ requestKey, generation: requestGeneration });
    setMoreError(null);
    try {
      const next = new URLSearchParams(query);
      next.set("cursor", current.cursor);
      const result = await discoveryApi.search(
        next.toString(),
        controller.signal,
      );
      if (generation.current !== requestGeneration) return;
      setData((previous) =>
        previous?.query === query && previous.generation === requestGeneration
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
      if (generation.current !== requestGeneration) return;
      setMoreError({
        query,
        generation: requestGeneration,
        message: e instanceof Error ? e.message : "Could not load more stays.",
      });
    } finally {
      if (generation.current === requestGeneration) {
        moreRequest.current = null;
        setMoreQuery(null);
      }
    }
  }
  function selectCategory(value: string) {
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (value) next.set("category", value);
    else next.delete("category");
    setParams(next);
  }
  const values = searchValues(params);
  return (
    <main
      className={`page-container discovery-page ${explore ? "explore-page" : ""} ${mapView ? "map-discovery-page" : ""}`}
    >
      <div className={`explore-intro ${explore ? "" : "results-intro"}`}>
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
        <SearchForm
          key={query}
          initial={values}
          joined
          preserveQuery={query}
          category={category}
        />
      </div>
      <div className="discovery-toolbar">
        {explore ? (
          <nav className="stay-categories" aria-label="Stay categories">
            {STAY_CATEGORIES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                aria-pressed={category === value}
                onClick={() => selectCategory(value)}
              >
                <StayIcon name={value} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
        ) : (
          <label className="results-category-control">
            <span>Category</span>
            <select
              className="results-category-select"
              aria-label="Stay category"
              value={category}
              onChange={(event) => selectCategory(event.target.value)}
            >
              {!STAY_CATEGORIES.some(({ value }) => value === category) && (
                <option value={category}>Unsupported category</option>
              )}
              {STAY_CATEGORIES.map(({ value, label }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        <Button
          variant="secondary"
          className="filters-trigger"
          aria-label={
            activeFilterCount(params)
              ? `Filters (${activeFilterCount(params)} active)`
              : "Filters"
          }
          aria-haspopup="dialog"
          aria-expanded={filtersOpen}
          onClick={() => setFiltersOpen(true)}
        >
          <StayIcon name="filters" />
          Filters
          {activeFilterCount(params) > 0 && (
            <span className="filters-count">{activeFilterCount(params)}</span>
          )}
        </Button>
      </div>
      {!explore && (
        <div className="map-search-toolbar">
          <div
            className="map-view-switch"
            role="group"
            aria-label="Results view"
          >
            <Button
              variant={mapView ? "secondary" : "primary"}
              aria-pressed={!mapView}
              onClick={() => switchView("list")}
            >
              List
            </Button>
            <Button
              variant={mapView ? "primary" : "secondary"}
              aria-pressed={mapView}
              onClick={() => switchView("map")}
            >
              Map
            </Button>
          </div>
          {mapView && (
            <>
              <label className="map-auto-search">
                <input
                  type="checkbox"
                  checked={autoSearch}
                  onChange={(event) => {
                    const next = new URLSearchParams(params);
                    next.set("move", String(event.target.checked));
                    setParams(next);
                  }}
                />
                Search as I move the map
              </label>
              {!autoSearch && (
                <Button
                  variant="secondary"
                  disabled={!draftBounds}
                  onClick={() => {
                    if (draftBounds) searchArea(draftBounds);
                  }}
                >
                  Search this area
                </Button>
              )}
              <p className="map-search-help">
                {bounds
                  ? "Searching this map area instead of the destination. Dates, guests and filters still apply."
                  : "Showing mapped stays matching your destination. Move the map to search another area."}{" "}
                Locations are approximate.{" "}
                <button
                  type="button"
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    for (const key of ["west", "south", "east", "north"])
                      next.delete(key);
                    next.set("move", "false");
                    setDraftBounds(null);
                    setParams(next);
                  }}
                >
                  Reset to destination
                </button>
              </p>
            </>
          )}
        </div>
      )}
      {filtersOpen && (
        <FiltersDrawer
          params={params}
          onClose={() => setFiltersOpen(false)}
          onApply={(draft) => {
            setParams(applyFilters(params, draft));
            setFiltersOpen(false);
          }}
        />
      )}
      {mapView && (
        <div className="mobile-map-feedback" aria-live="polite">
          {error ? (
            <ErrorState message={error} retry={() => setAttempt(attempt + 1)} />
          ) : !current ? (
            <p>Loading mapped stays…</p>
          ) : !current.items.length ? (
            <p>
              No mapped stays match this area and your filters. Try another
              area, or List for stays without saved locations.
            </p>
          ) : (
            <p>
              {current.items.length} mapped stays shown.{" "}
              {current.truncated
                ? "Result limit reached; zoom in or narrow your filters."
                : "Up to 50 results."}
            </p>
          )}
        </div>
      )}
      <div className={mapView ? "results-map-layout" : ""}>
        <div className="results-list-panel">
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
              Try adjusting your filters, destination, guests or dates.
            </EmptyState>
          ) : (
            <>
              <div className="results-heading">
                <h2>
                  {explore
                    ? "Places to make your own"
                    : `${current.items.length} ${current.items.length === 1 ? "stay" : "stays"} shown`}
                </h2>
                <p className="muted">
                  {values.check_in && values.check_out
                    ? "Stay totals include cleaning and the StayHub service fee."
                    : explore
                      ? `${current.items.length} ${current.items.length === 1 ? "stay" : "stays"} shown · Choose dates for the full stay price.`
                      : "Choose dates for the full stay price."}
                </p>
              </div>
              {mapView && (
                <p className="map-results-notice" role="status">
                  {current.truncated
                    ? "Result limit reached (up to 50 mapped stays). Zoom in or narrow your filters; more matching stays may exist."
                    : "Up to 50 mapped stays. Stays without a saved location are available in List view."}
                </p>
              )}
              <div
                className={explore ? "public-stay-grid" : "public-stay-results"}
              >
                {current.items.map((listing) => (
                  <article
                    key={listing.id}
                    className={`public-stay-card ${explore ? "" : "result-row"} ${mapView && selected === listing.id ? "map-selected-card" : ""}`}
                    data-listing-id={listing.id}
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
                      <Link
                        to={`/stays/${listing.id}${query ? `?${query}` : ""}`}
                      >
                        <h2>{listing.title}</h2>
                      </Link>
                      <p className="muted">
                        {listing.destination} ·{" "}
                        {listing.property_type === "room"
                          ? "Private room"
                          : `Entire ${listing.property_type}`}{" "}
                        · {listing.capacity} guests · {listing.beds}{" "}
                        {listing.beds === 1 ? "bed" : "beds"} · {listing.baths}{" "}
                        {listing.baths === 1 ? "bath" : "baths"}
                      </p>
                      {mapView && (
                        <button
                          className="show-stay-pin"
                          type="button"
                          aria-pressed={selected === listing.id}
                          onClick={() => setSelectedId(listing.id)}
                        >
                          Show on map
                          <span className="sr-only">: {listing.title}</span>
                        </button>
                      )}
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
                            <span>
                              {" "}
                              total · {listing.stay_price.nights} nights
                            </span>
                          </p>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              {moreError?.query === query &&
                moreError.generation === current.generation && (
                  <ErrorState
                    message={moreError.message}
                    retry={() => void more()}
                  />
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
        </div>
        {mapView && (
          <ResultsMapPanel
            items={current?.items ?? []}
            selected={selected}
            onSelect={setSelectedId}
            onBounds={setDraftBounds}
            bounds={bounds}
            query={query}
            onList={() => switchView("list")}
          />
        )}
      </div>
    </main>
  );
}
