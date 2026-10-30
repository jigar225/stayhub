import { useState } from "react";
import { useNavigate } from "react-router";
import { Button, ErrorState } from "../components/ui";
import { listingsApi } from "./api";
export function NewListing() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create() {
    setBusy(true);
    try {
      const data = await listingsApi.create();
      navigate(`/host/listings/${data.listing.id}/edit`, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a draft.");
      setBusy(false);
    }
  }
  return (
    <main className="host-content">
      <section className="card new-listing">
        <h1>Let’s make room for your place</h1>
        <p>
          Start a draft, add your details and photos, then publish when you’re
          ready. Your work is saved to your account.
        </p>
        {error && (
          <ErrorState
            message={`${error} Check your listings before creating another draft.`}
          />
        )}
        <Button disabled={busy} onClick={() => void create()}>
          {busy ? "Creating…" : "Start a listing"}
        </Button>
      </section>
    </main>
  );
}
