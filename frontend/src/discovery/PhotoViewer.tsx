import { useEffect, useId, useRef } from "react";
import { Button } from "../components/ui";
import type { PublicPhoto } from "./api";

export function PhotoViewer({
  photos,
  title,
  index,
  onIndex,
  onClose,
  onError,
}: {
  photos: PublicPhoto[];
  title: string;
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
  onError: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const safeIndex = Math.min(index, photos.length - 1);
  useEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog?.showModal();
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
      opener?.focus();
    };
  }, []);
  function move(delta: number) {
    onIndex((safeIndex + delta + photos.length) % photos.length);
  }
  return (
    <dialog
      ref={ref}
      className="photo-viewer-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          move(event.key === "ArrowLeft" ? -1 : 1);
        }
        if (event.key === "Home") {
          event.preventDefault();
          onIndex(0);
        }
        if (event.key === "End") {
          event.preventDefault();
          onIndex(photos.length - 1);
        }
        if (event.key === "Tab") {
          const buttons = Array.from(
            ref.current?.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ) ?? [],
          );
          const first = buttons[0],
            last = buttons[buttons.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <header className="photo-viewer-heading">
        <h2 id={titleId}>{title} · Photos</h2>
        <Button
          type="button"
          variant="secondary"
          aria-label="Close photo viewer"
          onClick={onClose}
        >
          Close ×
        </Button>
      </header>
      <div className="photo-viewer-stage">
        <img
          key={`${photos[safeIndex]?.id}-${photos[safeIndex]?.url}`}
          src={photos[safeIndex]?.url}
          alt={`${title}, photo ${safeIndex + 1}`}
          onError={onError}
        />
      </div>
      <div className="photo-viewer-controls">
        <Button
          type="button"
          variant="secondary"
          aria-label="Previous photo"
          disabled={photos.length < 2}
          onClick={() => move(-1)}
        >
          ← Previous
        </Button>
        <p role="status">
          Photo {safeIndex + 1} of {photos.length}
        </p>
        <Button
          type="button"
          variant="secondary"
          aria-label="Next photo"
          disabled={photos.length < 2}
          onClick={() => move(1)}
        >
          Next →
        </Button>
      </div>
      <div className="photo-viewer-thumbnails" aria-label="Choose a photo">
        {photos.map((photo, item) => (
          <button
            type="button"
            key={photo.id}
            aria-label={`View photo ${item + 1}`}
            aria-current={item === safeIndex ? "true" : undefined}
            onClick={() => onIndex(item)}
          >
            <img src={photo.url} alt="" loading="lazy" onError={onError} />
          </button>
        ))}
      </div>
    </dialog>
  );
}
