# Reservation communication and reviews

Additive migration `0008_communication` follows `0007_listing_location`.
It creates `conversations`, `messages`, `message_reads`, `message_attachments`,
`reviews`, `review_windows`, and `notifications`; adds nullable
`reservations.completed_at`; backfills completed reservations from their
completion audit event (scheduled checkout fallback); and inserts missing v1
policy catalog rows without rewriting existing definitions or snapshots.
No reservation money, status, payment, refund or payout record is rewritten.

## Authorization and time

Every private operation verifies the live session, membership and reservation
party. Only the booked guest and owning host have conversation/review access;
Admin has no implicit bypass. Notifications are recipient-only. Public listing
reviews require a published listing and contain only published guest reviews.
Auth/upload/read capabilities use real time. Review eligibility/deadlines use
business time. Review publication never changes reservation state or money.

## Messaging API

- `GET /api/v1/conversations?role=guest|host&limit=30&cursor=UUID`: inbox,
  unread count and last-message preview. One lazy conversation per reservation.
- `GET /api/v1/reservations/{id}/messages?limit=30&before=sequence`: latest
  history, ascending within a page, next older cursor and acknowledged cursor.
- `POST .../messages`: `{text, attachment_ids}` and `Idempotency-Key` (8–128
  characters). Text at most4000 characters; at most3 photos. Same actor/key/
  payload replays; changed payload conflicts. Reservation lock serializes sends,
  sequence allocation and lazy creation. No duplicate on dropped responses.
- `POST .../messages/read`: `{acknowledged_cursor}`. Signed one-hour cursor
  binds recipient, reservation and exact loaded message IDs. Unloaded old rows
  and messages arriving after that fetch remain unread. Read rows are idempotent.
- `POST .../messages/attachments`: `{content_type,bytes}` gives a private
  upload authorization. `POST .../messages/attachments/{id}/complete` verifies
  actual bytes, size, image format/dimensions and strips metadata into a new
  immutable object before attachment. No caller-supplied storage key/URL.

Photos allow JPEG/PNG/WebP, at most10MiB,20million pixels and8192px per side,
matching existing storage verification. Up to12 unfinished slots per owner/
reservation, each valid30minutes. Only their owner can attach them to that
reservation, once. Reads require party authorization and produce five-minute
signed URLs; an issued URL is a bearer capability until expiry. Original staged
bytes and expired unsent images are handled by scoped storage cleanup; sent
verified photos are retained. Browser text uses React text nodes, never HTML.
Polling runs only on mounted visible inbox/conversation UI and stops on logout.

## Reviews API and rules

- `GET/POST /api/v1/reservations/{id}/reviews`: party status and immutable
  submission. Guest input includes overall1–5, all six category ratings1–5
  (cleanliness, accuracy, check_in, communication, location, value), and public
  text1–3000 characters. Host submits text only, describing the guest.
- `GET /api/v1/listings/{id}/reviews?limit=20&cursor=UUID`: paginated published
  guest reviews plus overall average/count. Host reviews never affect aggregates.

A reservation must be completed, with distinct parties. Submission is allowed
strictly before `completed_at +14days`; the exact deadline is closed. One review
per reservation/author and role is enforced in PostgreSQL. All submissions are
immutable, including while private. Until both submit or the window closes,
only the actor's own review is returned; counterpart content/rating/presence is
not exposed. Both-party publication is in the second submission transaction.
The existing lifecycle sweep publishes expired windows under the same reservation
lock, so submit/publication races serialize. Durable window checkpoints avoid
repeating eligibility, reminders or closure. Sweeps preserve completed state and
financial values and expose `has_more` for remaining review batches.

## Notifications API and guarantees

- `GET /api/v1/me/notifications?before=id&limit=30`: recipient list, unread
  count and cutoff. `POST /{id}/read {}` marks that recipient's item read.
- `POST /api/v1/me/notifications/read-all {cutoff}` acknowledges IDs through
  the loaded cutoff. Later arrivals remain unread; UI reloads the projection.

New message, accepted/declined/expired reservation, cancellation, review
eligibility/publication and one48-hour reminder generate notifications in their
source transaction. Actor notifications are suppressed. Generic review notices
never reveal hidden text or scores. Unique(recipient,kind,source_key) plus
conflict-safe insertion deduplicates replays/sweep retries. A small transaction-
scoped advisory lock serializes notification identity allocation through commit,
so a later-committed notice cannot appear below an acknowledged cutoff.
No network delivery, email, SMS, push or WebSocket infrastructure is introduced.

## Host setup and rollout

`GET /api/v1/host/timezones` exposes supported IANA choices, including UTC and
aliases. Explicit runtime `tzdata` supplies aliases omitted by slim system
packages, also for booking/date calculations. The searchable selector preserves
saved values, supports keyboard selection and offers browser timezone only as an
explicit suggestion. No fixed offset is presented as year-round truth.

Policy descriptions for host setup, public detail and new booking terms derive
from persisted version definitions. Four policies remain available. Refund
percentages apply separately to nights and guest service fees; cleaning is fully
refunded before check-in. Existing booked snapshots and refund arithmetic remain
unchanged. Host edits affect future bookings.

Build the backend with the frozen lock, back up the database, apply the migration
once, and roll out API and lifecycle worker with matching source. Release the
frontend with the new endpoints. Preserve existing private storage and trusted-
origin CORS. No seed/reset, new infrastructure or new secret is required.
