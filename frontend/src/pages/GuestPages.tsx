import { useEffect, useState } from "react";
import { authenticated } from "../api/client";
import type { User } from "../api/types";
import { ErrorState } from "../components/ui";
export function ProfilePage() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const load = () => {
    setError("");
    void authenticated<{ user: User }>("/auth/me")
      .then((data) => setUser(data.user))
      .catch((e) =>
        setError(
          e instanceof Error ? e.message : "Could not load your profile.",
        ),
      );
  };
  useEffect(() => {
    let active = true;
    void authenticated<{ user: User }>("/auth/me")
      .then((data) => {
        if (active) setUser(data.user);
      })
      .catch((e) => {
        if (active)
          setError(
            e instanceof Error ? e.message : "Could not load your profile.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  if (error)
    return (
      <main className="page-container">
        <ErrorState message={error} retry={load} />
      </main>
    );
  if (!user)
    return (
      <main className="page-container" role="status">
        Loading your profile…
      </main>
    );
  return (
    <main className="page-container profile-page">
      <div className="page-heading">
        <h1>Profile</h1>
        <p>Your StayHub account, all in one place.</p>
      </div>
      <div className="profile-grid">
        <aside className="profile-summary">
          <span className="avatar large">
            {user.name.slice(0, 2).toUpperCase()}
          </span>
          <h2>{user.name}</h2>
          <div className="badges">
            {user.roles.map((role) => (
              <span className="badge" key={role}>
                {role.charAt(0).toUpperCase() + role.slice(1)}
              </span>
            ))}
          </div>
        </aside>
        <section className="card personal-info">
          <h2>Personal information</h2>
          <dl>
            <div>
              <dt>Full name</dt>
              <dd>{user.name}</dd>
            </div>
            <div>
              <dt>Email address</dt>
              <dd>{user.email}</dd>
            </div>
            <div>
              <dt>Account memberships</dt>
              <dd>
                {user.roles
                  .map((role) => role.charAt(0).toUpperCase() + role.slice(1))
                  .join(" · ")}
              </dd>
            </div>
          </dl>
          <p className="muted">
            Your account details are private. Profile editing will be available
            in a later milestone.
          </p>
        </section>
      </div>
    </main>
  );
}
