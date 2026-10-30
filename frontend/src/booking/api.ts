import { authenticated, ApiError } from "../api/client";
import type {
  PolicyTerms,
  PriceBreakdown,
  PublicPhoto,
} from "../discovery/api";
export interface Reservation {
  id: string;
  code: string;
  listing_id: string;
  guest_id: string;
  host_id: string;
  state:
    | "pending"
    | "confirmed"
    | "checked_in"
    | "completed"
    | "declined"
    | "cancelled_by_guest"
    | "cancelled_by_host";
  reason: string | null;
  booking_mode: "instant" | "request";
  check_in: string;
  check_out: string;
  guests: number;
  timezone: string;
  scheduled_check_in: string;
  scheduled_check_out: string;
  created_at: string;
  request_deadline: string | null;
  listing_snapshot: {
    title: string;
    destination: string;
    property_type: string;
    description: string;
    amenities: string[];
    house_rules: string[];
    host_name: string;
  };
  policy: PolicyTerms & { definition: Record<string, unknown> };
  price: PriceBreakdown;
  financial_version?: number;
  effective_host_fee_minor?: number;
  cancelled_at?: string | null;
  payout?: Payout | null;
  host_fee_minor: number;
  host_entitlement_minor: number;
  platform_entitlement_minor: number;
  payment: {
    id: string;
    amount_minor: number;
    currency: "EUR";
    paid_at: string;
  };
  refund: null | {
    id: string;
    amount_minor: number;
    nights_minor: number;
    cleaning_minor: number;
    guest_fee_minor: number;
    reason: string;
    refunded_at: string;
  };
}
export interface ReservationPage {
  items: Reservation[];
  next_cursor: string | null;
}
export interface TodayData {
  pending: Reservation[];
  upcoming: Reservation[];
  hosting: Reservation[];
  checkouts: Reservation[];
  next_cursor: string | null;
}
export function bookingError(error: unknown) {
  if (error instanceof ApiError && error.details.field_errors)
    return `${error.message} ${Object.values(error.details.field_errors).flat().join(" ")}`;
  return error instanceof Error
    ? error.message
    : "Could not complete this request.";
}
export interface Payout {
  id: string;
  reservation_id: string;
  code: string;
  listing_title: string;
  host_id: string;
  due_at: string;
  gross_minor: number;
  host_fee_minor: number;
  net_minor: number;
  status: "held" | "scheduled" | "paid" | "cancelled";
  paid_at: string | null;
  retained_cancellation: boolean;
}
export interface CancellationPreview {
  reservation_id: string;
  state: Reservation["state"];
  financial_version: number;
  policy_name: string;
  policy_version: number;
  refund_percent: number;
  nights_refund_minor: number;
  cleaning_refund_minor: number;
  guest_fee_refund_minor: number;
  total_refund_minor: number;
  retained_nights_minor: number;
  retained_guest_fee_minor: number;
  effective_host_fee_minor: number;
  host_entitlement_minor: number;
  platform_entitlement_minor: number;
  explanation: string;
  expires_at: string;
  confirmation_token: string;
}
export interface EarningsData {
  totals: { paid_minor: number; upcoming_minor: number; held_minor: number };
  items: Payout[];
  next_cursor: string | null;
}
export const bookingApi = {
  cancellationPreview: (id: string) =>
    authenticated<{ preview: CancellationPreview }>(
      `/reservations/${id}/cancellation-quote`,
      { method: "POST", body: "{}" },
    ),
  cancel: (id: string, confirmation_token: string, key: string) =>
    authenticated<{ reservation: Reservation }>(`/reservations/${id}/cancel`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ confirmation_token }),
    }),
  hostCancel: (id: string, reason: string, key: string) =>
    authenticated<{ reservation: Reservation }>(
      `/host/reservations/${id}/cancel`,
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({ reason }),
      },
    ),
  earnings: (status: string, cursor?: string) =>
    authenticated<EarningsData>(
      `/host/earnings?${new URLSearchParams({ ...(status ? { status } : {}), ...(cursor ? { cursor } : {}) })}`,
    ),
  pay: (quote_token: string, key: string) =>
    authenticated<{ reservation: Reservation }>("/reservations", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ quote_token }),
    }),
  trips: (category: string, cursor?: string) =>
    authenticated<ReservationPage>(
      `/me/reservations?${new URLSearchParams({ category, ...(cursor ? { cursor } : {}) })}`,
    ),
  detail: (id: string) =>
    authenticated<{ reservation: Reservation }>(`/reservations/${id}`),
  photos: (id: string) =>
    authenticated<{ items: PublicPhoto[] }>(`/reservations/${id}/photos`),
  today: (cursor?: string) =>
    authenticated<TodayData>(
      `/host/today${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  decide: (
    id: string,
    decision: "accept" | "decline",
    key: string,
    reason?: string,
  ) =>
    authenticated<{ reservation: Reservation }>(
      `/host/reservations/${id}/${decision}`,
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(decision === "decline" ? { reason } : {}),
      },
    ),
};
