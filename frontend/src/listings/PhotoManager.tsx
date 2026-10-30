import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  listingsApi,
  uploadFile,
  type Listing,
  type UploadIntent,
} from "./api";
import { PhotoImage } from "./PhotoImage";
import { Button, ErrorState } from "../components/ui";
export interface UploadJob {
  file: File;
  intent: UploadIntent | null;
  phase: "queued" | "uploading" | "verifying" | "done" | "failed";
  progress: number;
  error: string;
  uploaded: boolean;
  restart: boolean;
}
export function PhotoManager({
  listing,
  onChange,
  disabled,
  onBusy,
}: {
  listing: Listing;
  onChange: (listing: Listing) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const [working, setWorking] = useState(false);
  function lock(value: boolean) {
    busy.current = value;
    setWorking(value);
    onBusy(value);
  }
  function update(job: UploadJob) {
    setJobs((current) =>
      current.map((item) => (item.file === job.file ? { ...job } : item)),
    );
  }
  async function run(job: UploadJob) {
    job.error = "";
    try {
      if (!job.intent)
        job.intent = await listingsApi.intent(listing.id, job.file);
      if (!job.uploaded) {
        job.phase = "uploading";
        update(job);
        await uploadFile(job.file, job.intent, (progress) => {
          job.progress = progress;
          update(job);
        });
        job.uploaded = true;
      }
      job.phase = "verifying";
      update(job);
      const data = await listingsApi.complete(listing.id, job.intent.photo_id);
      onChange(data.listing);
      job.phase = "done";
      job.progress = 100;
      update(job);
    } catch (e) {
      job.phase = "failed";
      job.restart =
        !job.uploaded || (e instanceof ApiError && e.status === 422);
      job.error =
        e instanceof Error ? e.message : "Upload failed. Please retry.";
      update(job);
    } finally {
      try {
        onChange((await listingsApi.read(listing.id)).listing);
      } catch {
        setError(
          "Could not refresh the saved photo state. Save may need version recovery before continuing.",
        );
      }
    }
  }
  async function choose(files: FileList | null) {
    if (!files || busy.current || disabled) return;
    setError("");
    const incoming: UploadJob[] = [];
    for (const file of Array.from(files)) {
      if (
        !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
        file.size < 1 ||
        file.size > 10485760
      ) {
        setError("Choose JPEG, PNG or WebP images up to 10 MiB each.");
        continue;
      }
      incoming.push({
        file,
        intent: null,
        phase: "queued",
        progress: 0,
        error: "",
        uploaded: false,
        restart: false,
      });
    }
    if (listing.photos.length + incoming.length > 20) {
      setError("A listing can have at most 20 photos. Choose fewer photos.");
      return;
    }
    setJobs((current) => [...current, ...incoming]);
    lock(true);
    try {
      for (const job of incoming) await run(job);
    } finally {
      lock(false);
    }
  }
  async function retry(job: UploadJob) {
    if (busy.current) return;
    lock(true);
    if (job.restart) {
      job.intent = null;
      job.uploaded = false;
      job.progress = 0;
      job.restart = false;
    }
    try {
      await run(job);
    } finally {
      lock(false);
    }
  }
  async function change(action: () => Promise<{ listing: Listing }>) {
    if (busy.current) return;
    setError("");
    lock(true);
    try {
      onChange((await action()).listing);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not update your photos.",
      );
    } finally {
      lock(false);
    }
  }
  function move(index: number, direction: number) {
    const ids = listing.photos.map((photo) => photo.id);
    const other = index + direction;
    [ids[index], ids[other]] = [ids[other], ids[index]];
    void change(() => listingsApi.reorder(listing.id, listing.version, ids));
  }
  return (
    <section className="photo-manager">
      <div className="section-heading">
        <div>
          <h2>Photos</h2>
          <p className="muted">
            {listing.photos.length} verified · at least 5 to publish · up to 20
            photos
          </p>
        </div>
      </div>
      <label className="upload-control">
        Add photos
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          disabled={disabled || working}
          onChange={(event) => {
            void choose(event.target.files);
            event.target.value = "";
          }}
        />
      </label>
      <p className="field-help">
        JPEG, PNG or WebP · up to 10 MiB per photo. Photos are verified before
        they appear. First photo is the cover.
      </p>
      {error && <ErrorState message={error} />}
      <div className="photo-grid">
        {listing.photos.map((photo, index) => (
          <article className="photo-tile" key={photo.id}>
            <div className="photo-tile-image">
              <PhotoImage
                listingId={listing.id}
                photo={photo}
                alt={`Listing photo ${index + 1}`}
              />
              <span className="photo-position">
                {index === 0 ? "Cover" : index + 1}
              </span>
            </div>
            <div className="photo-tile-actions">
              <Button
                variant="secondary"
                aria-label={`Move photo ${index + 1} earlier`}
                disabled={disabled || working || index === 0}
                onClick={() => move(index, -1)}
              >
                ←
              </Button>
              <Button
                variant="secondary"
                aria-label={`Move photo ${index + 1} later`}
                disabled={
                  disabled || working || index === listing.photos.length - 1
                }
                onClick={() => move(index, 1)}
              >
                →
              </Button>
              <Button
                variant="ghost"
                aria-label={`Remove photo ${index + 1}`}
                disabled={disabled || working}
                onClick={() =>
                  void change(() => listingsApi.remove(listing.id, photo.id))
                }
              >
                Remove
              </Button>
            </div>
          </article>
        ))}
      </div>
      {jobs
        .filter((job) => job.phase !== "done")
        .map((job, index) => (
          <div className="upload-job" key={`${job.file.name}-${index}`}>
            <strong>{job.file.name}</strong>
            <span role="status">
              {job.phase === "failed"
                ? "Upload needs attention"
                : job.phase === "verifying"
                  ? "Verifying photo…"
                  : `${job.progress}% uploaded`}
            </span>
            <progress
              max={100}
              value={job.progress}
              aria-label={`Upload progress for ${job.file.name}`}
            />
            {job.error && <p role="alert">{job.error}</p>}
            {job.phase === "failed" && (
              <Button
                variant="secondary"
                disabled={working || disabled}
                onClick={() => void retry(job)}
              >
                {job.restart
                  ? "Restart photo upload"
                  : job.uploaded
                    ? "Retry verification"
                    : "Retry upload"}
              </Button>
            )}
          </div>
        ))}
    </section>
  );
}
