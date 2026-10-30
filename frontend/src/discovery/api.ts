import { refreshBusinessTime } from "../api/businessTime";
import { publicRequest } from "../api/client";
export interface PublicPhoto {
  id: string;
  url: string;
  expires_at: string;
  width: number;
  height: number;
}
export interface PriceBreakdown {
  nights: number;
  nightly_minor: number;
  nights_minor: number;
  cleaning_minor: number;
  subtotal_minor: number;
  guest_fee_minor: number;
  total_minor: number;
  currency: "EUR";
}
export interface PolicyTerms {
  id: string;
  name: string;
  version: number;
  terms: string;
}
export interface PublicSummary {
  id: string;
  title: string;
  destination: string;
  property_type: string;
  capacity: number;
  bedrooms: number;
  beds: number;
  baths: number;
  nightly_minor: number;
  cleaning_minor: number;
  booking_mode: "instant" | "request";
  photos: PublicPhoto[];
  stay_price: PriceBreakdown | null;
  demo_label: string | null;
}
export interface PublicDetail extends PublicSummary {
  description: string;
  amenities: string[];
  house_rules: string[];
  timezone: string;
  check_in_time: string;
  check_out_time: string;
  host_name: string;
  policy: PolicyTerms;
}
export interface Quote extends PriceBreakdown {
  listing_id: string;
  check_in: string;
  check_out: string;
  guests: number;
  booking_mode: "instant" | "request";
  policy: PolicyTerms;
  scheduled_check_in: string;
  scheduled_check_out: string;
  expires_at: string;
  quote_token: string;
}
export interface UnavailableRange {
  check_in: string;
  check_out: string;
}
export const discoveryApi = {
  search: (query: string, signal?: AbortSignal) =>
    publicRequest<{ items: PublicSummary[]; next_cursor: string | null }>(
      `/listings${query ? `?${query}` : ""}`,
      { signal },
    ),
  detail: (id: string, signal?: AbortSignal) =>
    publicRequest<{ listing: PublicDetail }>(`/listings/${id}`, { signal }),
  photos: (id: string) =>
    publicRequest<{ items: PublicPhoto[] }>(`/listings/${id}/photos`),
  availability: (
    id: string,
    start: string,
    end: string,
    signal?: AbortSignal,
  ) =>
    publicRequest<{
      listing_id: string;
      timezone: string;
      start: string;
      end: string;
      unavailable: UnavailableRange[];
    }>(`/listings/${id}/availability?${new URLSearchParams({ start, end })}`, {
      signal,
    }),
  quote: (
    id: string,
    dates: { check_in: string; check_out: string; guests: number },
  ) =>
    publicRequest<{ quote: Quote }>("/booking-quotes", {
      method: "POST",
      body: JSON.stringify({ listing_id: id, ...dates }),
    }).catch((error) => {
      void refreshBusinessTime();
      throw error;
    }),
};
