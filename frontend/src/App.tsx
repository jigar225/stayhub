import { HostReviews } from "./reviews/HostReviews";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router";
import { bootstrap, refresh } from "./api/client";
import { useSession } from "./auth/useSession";
import { GuestShell } from "./components/GuestShell";
import { Button, ErrorState } from "./components/ui";
import { AuthPage } from "./pages/AuthPage";
import { ProfilePage } from "./pages/GuestPages";
import { Earnings } from "./booking/Earnings";
import { Cancellation } from "./booking/Cancellation";
import { refreshBusinessTime } from "./api/businessTime";
import { AdminPage } from "./pages/AdminPage";
import { HostShell } from "./components/HostShell";
import { ListingCards } from "./listings/ListingCards";
import { ListingWizard } from "./listings/ListingWizard";
import { ListingPreview } from "./listings/ListingPreview";
import { NewListing } from "./listings/NewListing";
import { StayResults } from "./discovery/StayResults";
import { StayDetail } from "./discovery/StayDetail";
import { Checkout } from "./booking/Checkout";
import { Trips, TripDetail } from "./booking/Trips";
import { HostToday } from "./booking/HostToday";
import { HostReservations } from "./booking/HostReservations";
import { clearOtherActorActions } from "./booking/actionRecovery";
import { readSubmission } from "./booking/recovery";
import { HostCalendar } from "./calendar/HostCalendar";
import { Notifications } from "./notifications/Notifications";
import { Messages, Inbox } from "./communication/Messages";
import { ReviewForm } from "./reviews/ReviewForm";
function Protected({
  children,
  role,
}: {
  children: ReactNode;
  role?: "host" | "admin";
}) {
  const { user, ready, error } = useSession();
  const location = useLocation();
  const [admitted, setAdmitted] = useState(false);
  if (user && (!role || user.roles.includes(role)) && !admitted)
    setAdmitted(true);
  // Keep only an already-admitted editor mounted across expiry so it can hide
  // private content and offer in-place reauthentication without losing edits.
  if (admitted && /^\/host\/listings\/[^/]+\/edit$/.test(location.pathname))
    return children;
  if (!ready)
    return (
      <main className="page-container" role="status">
        Restoring your session…
      </main>
    );
  if (error)
    return (
      <main className="page-container">
        <ErrorState
          message={error}
          retry={() => void refresh().catch(() => {})}
        />
      </main>
    );
  if (!user)
    return (
      <Navigate
        to={`/login?returnTo=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  if (role && !user.roles.includes(role))
    return (
      <main className="page-container">
        <h1>Access is limited</h1>
        <p>This workspace requires a {role} membership.</p>
        <Link to="/profile" className="button secondary">
          View your profile
        </Link>
      </main>
    );
  return <Fragment key={user.id}>{children}</Fragment>;
}
export function App() {
  const { user } = useSession();
  const location = useLocation();
  useEffect(() => {
    void refreshBusinessTime();
  }, [location.pathname, location.search]);
  useEffect(() => {
    if (user) {
      readSubmission(user.id);
      clearOtherActorActions(user.id);
    }
  }, [user]);
  useEffect(() => {
    void bootstrap();
  }, []);
  return (
    <Routes>
      <Route element={<GuestShell />}>
        <Route
          path="notifications"
          element={
            <Protected>
              <Notifications />
            </Protected>
          }
        />
        <Route
          path="messages"
          element={
            <Protected>
              <Inbox />
            </Protected>
          }
        />
        <Route
          path="messages/:reservationId"
          element={
            <Protected>
              <Messages />
            </Protected>
          }
        />
        <Route
          path="trips/:id/review"
          element={
            <Protected>
              <ReviewForm />
            </Protected>
          }
        />
        <Route index element={<StayResults explore />} />
        <Route path="stays" element={<StayResults />} />
        <Route path="stays/:id" element={<StayDetail />} />
        <Route path="login" element={<AuthPage />} />
        <Route path="signup" element={<AuthPage signup />} />
        <Route
          path="profile"
          element={
            <Protected>
              <ProfilePage />
            </Protected>
          }
        />
        <Route
          path="trips"
          element={
            <Protected>
              <Trips />
            </Protected>
          }
        />
        <Route
          path="checkout/:listingId"
          element={
            <Protected>
              <Checkout />
            </Protected>
          }
        />
        <Route
          path="trips/:id/cancel"
          element={
            <Protected>
              <Cancellation />
            </Protected>
          }
        />
        <Route
          path="trips/:id"
          element={
            <Protected>
              <TripDetail />
            </Protected>
          }
        />
        <Route
          path="*"
          element={
            <main className="page-container">
              <h1>Page not found</h1>
              <Button onClick={() => window.location.assign("/")}>
                Back to Stays
              </Button>
            </main>
          }
        />
      </Route>
      <Route
        path="host"
        element={
          <Protected role="host">
            <HostShell />
          </Protected>
        }
      >
        <Route path="today" element={<HostToday />} />
        <Route path="reservations" element={<HostReservations />} />
        <Route path="reviews" element={<HostReviews />} />
        <Route path="calendar" element={<HostCalendar />} />
        <Route path="earnings" element={<Earnings />} />
        <Route path="listings" element={<ListingCards />} />
        <Route path="listings/new" element={<NewListing />} />
        <Route path="listings/:id/edit" element={<ListingWizard />} />
        <Route path="listings/:id/preview" element={<ListingPreview />} />
      </Route>
      <Route
        path="admin"
        element={
          <Protected role="admin">
            <AdminPage />
          </Protected>
        }
      />
    </Routes>
  );
}
