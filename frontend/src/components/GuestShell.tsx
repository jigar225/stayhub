import { useState } from "react";
import { Link, Outlet, useNavigate } from "react-router";
import { logout, startHosting } from "../api/client";
import { useSession } from "../auth/useSession";
import { Brand, Button, Dialog, ErrorState } from "./ui";
import { NotificationBell } from "../notifications/Notifications";
export function GuestShell() {
  const { user } = useSession();
  const navigate = useNavigate();
  const [menu, setMenu] = useState(false);
  const [enroll, setEnroll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function leave() {
    setBusy(true);
    setError("");
    try {
      await logout();
      setMenu(false);
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  async function enrollHost() {
    setBusy(true);
    setError("");
    try {
      await startHosting();
      setEnroll(false);
      navigate("/host/today");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="guest-header">
        <Link to="/" aria-label="StayHub home">
          <Brand />
        </Link>
        <Link to="/" className="stays-nav">
          Stays
        </Link>
        <nav className="guest-actions" aria-label="Account">
          {user ? (
            <>
              {!user.roles.includes("admin") && (
                <Button
                  variant="ghost"
                  onClick={() =>
                    user.roles.includes("host")
                      ? navigate("/host/today")
                      : setEnroll(true)
                  }
                >
                  Switch to hosting
                </Button>
              )}
              {user.roles.includes("admin") && <Link to="/admin">Admin</Link>}
              <NotificationBell />
              <div className="menu-anchor">
                <Button
                  variant="secondary"
                  aria-label="Account menu"
                  aria-expanded={menu}
                  onClick={() => setMenu(!menu)}
                >
                  <span className="avatar">
                    {user.name.slice(0, 2).toUpperCase()}
                  </span>
                  <span aria-hidden="true">⌄</span>
                </Button>
                {menu && (
                  <div className="account-menu">
                    <span className="menu-name">{user.name}</span>
                    <Link onClick={() => setMenu(false)} to="/trips">
                      Trips
                    </Link>
                    <Link onClick={() => setMenu(false)} to="/messages">
                      Messages
                    </Link>
                    <Link onClick={() => setMenu(false)} to="/profile">
                      Profile
                    </Link>
                    <Button
                      variant="ghost"
                      onClick={() => void leave()}
                      disabled={busy}
                    >
                      {busy ? "Logging out…" : "Log out"}
                    </Button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              <Link className="login-link" to="/login">
                Log in
              </Link>
              <Link className="button primary" to="/signup">
                Sign up
              </Link>
            </>
          )}
        </nav>
      </header>
      {error && !enroll && (
        <div className="page-container">
          <ErrorState message={error} />
        </div>
      )}
      <Outlet />
      {enroll && (
        <Dialog
          title="Start hosting on StayHub"
          onClose={() => !busy && setEnroll(false)}
        >
          <p>
            Add Host to your account to access your hosting workspace. You’ll
            keep your Guest membership and can switch back to traveling anytime.
          </p>
          <p className="muted">
            Create your first listing, manage availability and respond to guest
            requests.
          </p>
          {error && <ErrorState message={error} />}
          <div className="dialog-actions">
            <Button
              variant="secondary"
              onClick={() => setEnroll(false)}
              disabled={busy}
            >
              Not now
            </Button>
            <Button onClick={() => void enrollHost()} disabled={busy}>
              {busy ? "Starting…" : "Start hosting"}
            </Button>
          </div>
        </Dialog>
      )}
    </>
  );
}
