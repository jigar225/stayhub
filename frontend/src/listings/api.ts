import { authenticated } from "../api/client";
export type ListingStatus = "draft" | "published" | "unlisted";
export interface Photo {
  id: string;
  order: number;
  content_type: string;
  bytes: number;
  width: number;
  height: number;
}
export interface DraftFields {
  property_type: "apartment" | "house" | "room" | null;
  address: string | null;
  latitude?: number | null;
  longitude?: number | null;
  destination: string | null;
  timezone: string | null;
  capacity: number | null;
  bedrooms: number | null;
  beds: number | null;
  baths: number | null;
  title: string | null;
  description: string | null;
  amenities: string[] | null;
  categories?: string[] | null;
  house_rules: string[] | null;
  nightly_minor: number | null;
  cleaning_minor: number | null;
  policy_id: string | null;
  booking_mode: "instant" | "request" | null;
  check_in_time: string | null;
  check_out_time: string | null;
}
export interface Listing extends DraftFields {
  id: string;
  status: ListingStatus;
  version: number;
  created_at: string;
  updated_at: string;
  photos: Photo[];
}
export interface Policy {
  id: string;
  name: string;
  version: number;
}
export type ListingResponse = { listing: Listing };
export interface UploadIntent {
  photo_id: string;
  upload: { method: "PUT"; url: string; headers: Record<string, string> };
  expires_in: number;
}
export const listingsApi = {
  list: (cursor?: string) =>
    authenticated<{ items: Listing[]; next_cursor: string | null }>(
      `/host/listings${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  read: (id: string) => authenticated<ListingResponse>(`/host/listings/${id}`),
  create: () =>
    authenticated<ListingResponse>("/host/listings", {
      method: "POST",
      body: "{}",
    }),
  save: (id: string, version: number, fields: Partial<DraftFields>) =>
    authenticated<ListingResponse>(`/host/listings/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ version, ...fields }),
    }),
  publish: (id: string, version: number) =>
    authenticated<ListingResponse>(`/host/listings/${id}/publish`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  unlist: (id: string, version: number) =>
    authenticated<ListingResponse>(`/host/listings/${id}/unlist`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  policies: () =>
    authenticated<{ items: Policy[] }>("/host/cancellation-policies"),
  intent: (id: string, file: File) =>
    authenticated<UploadIntent>(`/host/listings/${id}/photos/upload-intents`, {
      method: "POST",
      body: JSON.stringify({ content_type: file.type, bytes: file.size }),
    }),
  complete: (id: string, photoId: string) =>
    authenticated<{ photo: Photo; listing: Listing }>(
      `/host/listings/${id}/photos/${photoId}/complete`,
      { method: "POST", body: "{}" },
    ),
  remove: (id: string, photoId: string) =>
    authenticated<ListingResponse>(`/host/listings/${id}/photos/${photoId}`, {
      method: "DELETE",
    }),
  reorder: (id: string, version: number, ids: string[]) =>
    authenticated<ListingResponse>(`/host/listings/${id}/photos/order`, {
      method: "PATCH",
      body: JSON.stringify({ version, photo_ids: ids }),
    }),
  image: (id: string, photoId: string) =>
    authenticated<{ url: string; expires_in: number }>(
      `/host/listings/${id}/photos/${photoId}/read`,
    ),
};
export function uploadFile(
  file: File,
  intent: UploadIntent,
  onProgress: (progress: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", intent.upload.url);
    for (const [key, value] of Object.entries(intent.upload.headers))
      xhr.setRequestHeader(key, value);
    xhr.timeout = 60000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(
            new Error(
              "Photo upload failed. Retry the upload before verifying.",
            ),
          );
    xhr.onerror = () =>
      reject(
        new Error(
          "Unable to upload the photo. Check your connection and retry.",
        ),
      );
    xhr.ontimeout = () =>
      reject(new Error("Photo upload timed out. Retry the upload."));
    xhr.send(file);
  });
}
