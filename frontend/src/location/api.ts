import { authenticated, publicRequest } from "../api/client";

export interface Point {
  latitude: number;
  longitude: number;
}
export interface Suggestion extends Point {
  display_address: string;
}
export interface ApproximateLocation extends Point {
  grid_degrees: number;
  radius_meters: number;
  max_zoom: number;
}
export const locationApi = {
  autocomplete: (query: string, signal: AbortSignal) =>
    authenticated<{ items: Suggestion[]; attribution: string }>(
      "/host/location/autocomplete",
      {
        method: "POST",
        body: JSON.stringify({ query }),
        signal,
      },
    ),
  publicLocation: (id: string, signal: AbortSignal) =>
    publicRequest<{ location: ApproximateLocation | null }>(
      `/listings/${id}/location`,
      { signal },
    ),
};
