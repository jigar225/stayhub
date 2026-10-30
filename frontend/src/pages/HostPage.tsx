import { Link } from "react-router";
import { EmptyState } from "../components/ui";
export function DeferredHostPage({ name }: { name: string }) {
  return (
    <main className="host-content">
      <h1>{name}</h1>
      <EmptyState
        title={`${name} is coming soon`}
        action={
          <Link className="button secondary" to="/host/today">
            Back to Today
          </Link>
        }
      >
        This workspace is part of a later milestone.
      </EmptyState>
    </main>
  );
}
