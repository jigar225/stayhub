import { useRef, useState } from "react";
import { Button } from "../components/ui";
import { discoveryApi, type PublicPhoto } from "./api";
import { PhotoViewer } from "./PhotoViewer";
export function PublicPhotos({
  listingId,
  photos: initial,
  title,
  gallery = false,
  renewPhotos,
}: {
  listingId: string;
  photos: PublicPhoto[];
  title: string;
  gallery?: boolean;
  renewPhotos?: () => Promise<{ items: PublicPhoto[] }>;
}) {
  const [photos, setPhotos] = useState(initial);
  const [viewing, setViewing] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const flight = useRef(false);
  const attempts = useRef(0);
  async function renew(manual = false) {
    if (flight.current) return;
    if (!manual && attempts.current >= 1) {
      setFailed(true);
      return;
    }
    flight.current = true;
    attempts.current++;
    setLoading(true);
    setFailed(false);
    try {
      const data = await (renewPhotos
        ? renewPhotos()
        : discoveryApi.photos(listingId));
      setPhotos(gallery ? data.items : data.items.slice(0, 1));
      if (!data.items.length) setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      flight.current = false;
      setLoading(false);
    }
  }
  if (failed)
    return (
      <div className="public-photo-error">
        <p>We couldn’t load the photos.</p>
        <Button variant="secondary" onClick={() => void renew(true)}>
          Retry photos
        </Button>
      </div>
    );
  if (!photos.length)
    return <div className="photo-placeholder">Photos are unavailable.</div>;
  return (
    <>
      <div
        className={gallery ? "public-gallery" : "public-cover"}
        aria-busy={loading}
      >
        {(gallery ? photos.slice(0, 5) : photos).map((photo, index) => (
          <div
            key={`${photo.id}-${photo.url}`}
            className={gallery && index === 0 ? "gallery-cover" : ""}
          >
            {gallery ? (
              <button
                type="button"
                className="gallery-photo-button"
                aria-label={`Open photo ${index + 1} of ${photos.length}`}
                onClick={() => setViewing(index)}
              >
                <img
                  src={photo.url}
                  alt={`${title}, photo ${index + 1}`}
                  onError={() => void renew()}
                  loading="eager"
                />
              </button>
            ) : (
              <img
                src={photo.url}
                alt={`${title}${gallery ? `, photo ${index + 1}` : ""}`}
                onError={() => void renew()}
                loading={gallery || index === 0 ? "eager" : "lazy"}
              />
            )}
          </div>
        ))}
        {gallery && (
          <Button
            type="button"
            variant="secondary"
            className="gallery-open-button"
            onClick={() => setViewing(0)}
          >
            Show all {photos.length} photos
          </Button>
        )}
        {loading && (
          <span className="photo-renew-status" role="status">
            Refreshing photo access…
          </span>
        )}
      </div>
      {viewing !== null && (
        <PhotoViewer
          photos={photos}
          title={title}
          index={viewing}
          onIndex={setViewing}
          onClose={() => setViewing(null)}
          onError={() => void renew()}
        />
      )}
    </>
  );
}
