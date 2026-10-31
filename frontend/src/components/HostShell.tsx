import { useRef } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { useSession } from "../auth/useSession";
import { Brand, Button } from "./ui";
import { NotificationBell } from "../notifications/Notifications";
export function HostShell() {
  const { user } = useSession();
  const drawer = useRef<HTMLDialogElement>(null);
  const location = useLocation();
  const section = location.pathname.includes("/reviews")
    ? "Reviews"
    : location.pathname.includes("/listings")
      ? "Listings"
      : location.pathname.includes("/reservations")
        ? "Reservations"
        : location.pathname.includes("/calendar")
          ? "Calendar"
          : location.pathname.includes("/earnings")
            ? "Earnings"
            : "Today";
  const navigation = (
    <nav>
      {["Today", "Calendar", "Listings", "Earnings"].map((name, index) => (
        <Link
          key={name}
          className={`button ghost ${section === name ? "selected" : ""}`}
          to={`/host/${name.toLowerCase()}`}
          onClick={() => drawer.current?.close()}
        >
          <span className="nav-icon" aria-hidden="true">
            {["⌂", "▦", "▤", "€"][index]}
          </span>
          {name}
        </Link>
      ))}
      <Link
        className="button ghost"
        to="/host/reservations"
        onClick={() => drawer.current?.close()}
      >
        Reservations
      </Link>
      <Link
        className={`button ghost ${section === "Reviews" ? "selected" : ""}`}
        to="/host/reviews"
        onClick={() => drawer.current?.close()}
      >
        Reviews
      </Link>
      <Link
        className="button ghost"
        to="/messages?role=host"
        onClick={() => drawer.current?.close()}
      >
        Inbox
      </Link>
    </nav>
  );
  return (
    <div className="host-layout">
      <aside className="host-sidebar" aria-label="Hosting navigation">
        <Link to="/" className="sidebar-brand">
          <Brand />
        </Link>
        <span className="sidebar-label">Hosting</span>
        {navigation}
        <div className="sidebar-user">
          <span className="avatar">{user?.name.slice(0, 2).toUpperCase()}</span>
          <div>
            <strong>{user?.name}</strong>
            <span>Guest · Host</span>
          </div>
        </div>
      </aside>
      <dialog
        ref={drawer}
        className="mobile-drawer"
        aria-label="Hosting navigation"
      >
        <div className="dialog-heading">
          <Brand />
          <Button
            variant="ghost"
            aria-label="Close hosting navigation"
            onClick={() => drawer.current?.close()}
          >
            ×
          </Button>
        </div>
        {navigation}
      </dialog>
      <div className="host-main">
        <header className="host-topbar">
          <Button
            variant="ghost"
            className="drawer-toggle"
            aria-label="Open hosting navigation"
            onClick={() => drawer.current?.showModal()}
          >
            ☰
          </Button>
          <span>
            Hosting / <strong>{section}</strong>
          </span>
          <Link to="/">Switch to traveling</Link>
          <Link to="/messages?role=host">Inbox</Link>
          <NotificationBell />
        </header>
        <Outlet />
      </div>
    </div>
  );
}
