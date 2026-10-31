import { authenticated, publicRequest } from "../api/client";

export const reviewCategories = {
  cleanliness: "Cleanliness",
  accuracy: "Accuracy",
  check_in: "Check-in",
  communication: "Communication",
  location: "Location",
  value: "Value",
} as const;
export interface Review {
  id: string;
  author_role: "guest" | "host";
  author_name: string;
  text: string;
  overall: number | null;
  categories: Record<string, number>;
  submitted_at: string;
  published_at: string | null;
}
export interface PartyReviews {
  reservation_id: string;
  listing_title: string;
  role: "guest" | "host";
  eligible: boolean;
  deadline: string | null;
  own: Review | null;
  counterpart: Review | null;
  status: "not_completed" | "open" | "submitted" | "published" | "closed";
}
export interface ListingReviewPage {
  items: Review[];
  average: number | null;
  count: number;
  next_cursor: string | null;
}
export const reviewApi = {
  party: (id: string) =>
    authenticated<PartyReviews>(`/reservations/${id}/reviews`),
  submit: (
    id: string,
    body: {
      text: string;
      overall?: number;
      categories?: Record<string, number>;
    },
  ) =>
    authenticated<PartyReviews>(`/reservations/${id}/reviews`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listing: (id: string, cursor?: string, signal?: AbortSignal) =>
    publicRequest<ListingReviewPage>(
      `/listings/${id}/reviews${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
      { signal },
    ),
};
