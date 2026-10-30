import { useEffect, useState } from "react";
import { listingsApi, type Photo } from "./api";
import { Button } from "../components/ui";
export function PhotoImage({
  listingId,
  photo,
  alt,
}: {
  listingId: string;
  photo: Photo;
  alt: string;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void listingsApi
      .image(listingId, photo.id)
      .then((data) => {
        if (active) {
          setUrl(data.url);
          setError(false);
        }
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [listingId, photo.id, attempt]);
  if (error)
    return (
      <div className="photo-placeholder">
        <span>Photo unavailable</span>
        <Button
          variant="secondary"
          onClick={() => {
            setError(false);
            setAttempt(attempt + 1);
          }}
        >
          Retry photo
        </Button>
      </div>
    );
  return url ? (
    <img src={url} alt={alt} onError={() => setError(true)} />
  ) : (
    <div className="photo-placeholder" role="status">
      Loading photo…
    </div>
  );
}
