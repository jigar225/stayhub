# StayHub — Milestones 1–6

Local React/Vite/TypeScript/Tailwind + FastAPI/SQLAlchemy/Alembic + PostgreSQL foundation. M1 implements accounts, sessions, Guest/Host membership, Profile and shells. M2 adds private host listing drafts, verified photos and publication. M3 adds host blocks, public discovery/detail, signed server price quotes and explicit licensed-photo demo content. M4 adds atomic simulated booking/payment, Trips and host requests; M5 adds cancellation/refunds, progression/payouts, earnings, admin events and persisted demo clock. M6 audits the complete local V1 experience and closes focused recovery/visual defects. Remote deployment remains deferred.

## Run locally

Prerequisites: Docker Desktop with Compose v2, Make, Node.js 24+ and npm for host browser checks, Python 3.13 for the restart check. Docker runs the application and quality tools.

1. Copy `.env.example` to `.env`; supply all required private values. Use URL-safe random `POSTGRES_PASSWORD` and a random `JWT_SECRET` of at least 32 characters, and private random `S3_ACCESS_KEY`/`S3_SECRET_KEY`. Keep the local endpoint/bucket settings from the example unless using an isolated override. Never commit `.env`.
2. Set all three separate seed email/password/name groups before running `seed-demo`/`seed-content`. Admin is a separate account; public signup always creates Guest.
3. Run `make dev-up`, then `make migrate`. Liveness is available before migration; readiness requires the database/schema.
4. Run `make seed-demo` explicitly (it includes `storage-init`), then `make seed-content` to provision the six fictional demo stays and30 licensed stored photos. Without `seed-content`, an empty installation has no demo stays. Reruns preserve existing content/credentials; content import creates an ordinary seed-Host auth session each time. Seeding never happens during application startup.
5. Open [StayHub](http://localhost:5173). API [health](http://localhost:8000/health), [readiness](http://localhost:8000/ready), and [OpenAPI](http://localhost:8000/docs) are available locally.

Guest route `/`, signup `/signup`, login `/login`, protected own Profile `/profile`, Host `/host/today`, and basic Admin landing are the M1 surface. Choose Start hosting and consent to add Host while retaining Guest. M2 enables `/host/listings` with saved drafts/editor/owner preview. M3 enables `/host/calendar`, `/stays` and `/stays/:id`; M4 enables checkout/Trips/Today; M5 adds `/trips/:id/cancel`, `/host/earnings` and Admin event/demo controls.

`make dev-down` stops services without removing the named database volume. Ordinary restarts preserve account/session data. Do not use `docker compose down -v` against data you want to retain. The test database is a separate ephemeral Compose service and never substitutes SQLite.

## Checks

```sh
make dev-up
make migrate
make seed-demo
make seed-content
make seed-content
make lint
make format-check
make typecheck
make test
make build
npm --prefix frontend ci
npx --prefix frontend playwright install chromium
make smoke-auth
make smoke-listings
make smoke-discovery
make restart-check
```

The frontend browser runtime must be installed on the host for `smoke-auth`. Root checks execute actual frontend/backend tooling; backend build validation imports the app and generates OpenAPI (Python has no asset compilation step). The test database is isolated as `stayhub_test` on `test-db`. HTTP/browser checks create uniquely named disposable accounts in the development database; they do not delete user data.

Current local acceptance, command outputs, screenshots and limitations are recorded in [M6 evidence](docs/m6-evidence.md) and the [V1 checklist](docs/m6-acceptance.md). Historical milestone results remain in their individual evidence documents. A passing automated build alone is not review acceptance.

## Configuration

`.env` supplies `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `JWT_SECRET`, `TRUSTED_ORIGINS`, `COOKIE_SECURE`, and `SEED_GUEST_EMAIL`, `SEED_GUEST_PASSWORD`, `SEED_GUEST_NAME`, corresponding `SEED_HOST_*` and `SEED_ADMIN_*`. No secret values belong in frontend variables.

Compose derives backend `DATABASE_URL` and `TEST_DATABASE_URL`. Frontend `API_PROXY_TARGET=http://api:8000` forwards `/api` from port 5173, preserving browser same-origin auth. Backend port 8000 is loopback bound. Frontend port 5173 is loopback bound. `TRUSTED_ORIGINS` must match the browser URL exactly. Local HTTP alone allows `COOKIE_SECURE=false`; HTTPS deployment must enable Secure cookies and same-origin routing. Deployment is not part of M1.

JWT settings and rate-limit tuning are documented with backend implementation evidence. Auth uses real UTC time independent of any future demo/business clock. Access tokens last 15 minutes and live only in frontend memory. Opaque refresh cookies expire absolutely after seven days; rotations retain consumed hashes and reuse revokes the session. Every protected request checks live session/account status and current database roles. Logout revokes issued access credentials and clears private frontend state only after server confirmation. Refresh/logout require session CSRF and exact trusted Origin; signup/login require trusted Origin and JSON. Argon2id hashes passwords. Rate limiting is bounded and single-process for this local milestone; multiple API replicas would require coordinated limits.

## Module boundaries

- `frontend/`: routing/pages, shared controls/tokens, API/session client, unit/browser tests, frontend dependency lock.
- `backend/`: transport/schema, authentication/security services, persistence/config, Alembic migrations, explicit seed module, Postgres tests, Python dependency lock.
- Root `compose.yaml`, `Makefile`, `.env.example`, `scripts/`: local orchestration and integration verification.
- `docs/`: approved scope, design/API authority and review evidence. The two role probe endpoints are documented in the API contract; they do not implement later host/admin operations.

No remote application deployment has been attempted. M6 is the current local review stop point; subsequent milestones and deployment are not authorized.

## Milestone 2 — host listings and verified photos

M2 adds host-only listing cards, a four-step saved-draft editor, owner preview, publish/unlist, and direct browser photo upload to private persistent S3-compatible storage. M3 extends this with discovery and calendar; booking and payments remain deferred. Exact schemas/validation/lifecycle are in [M2 contract](docs/m2-contract.md); actual review results are in [M2 evidence](docs/m2-evidence.md).

Supply the new server-side variables from `.env.example`: `S3_ACCESS_KEY`, `S3_SECRET_KEY` (random private local credentials), `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_BUCKET`, `TEST_S3_BUCKET`, `S3_REGION`. The browser receives only five-minute presigned URLs, never storage credentials. The internal endpoint is `http://storage:9000`; browser URL is `http://localhost:9000`, so open the app at `http://localhost:5173`. Do not substitute the Docker hostname in browser URLs. Bucket CORS permits only configured trusted frontend origins.

```sh
make dev-up
make migrate
make storage-init
make seed-demo
make smoke-listings
make persistence-listings
make storage-cleanup
```

`storage-init` explicitly creates private buckets/CORS; it does not set public ACLs/policies. Development uploads live on the named `object_data` volume. Never remove that volume as a test/reset. The isolated `TEST_S3_BUCKET` must end in `-test`; backend storage tests clean only their own isolated records/objects. Browser/persistence checks create unique demo records and retain them without touching user uploads. `persistence-listings` creates a unique draft with five actual images and checks metadata and SHA256 content across ordinary database/storage/API/frontend restarts.

Photo limits: JPEG/PNG/WebP,10MiB,20 active slots/listing (including pending intents),20million decoded pixels and8192px per dimension. Completion verifies actual bytes and re-encodes to a separate random final key, stripping metadata. Staging URL reuse never changes verified images. Only verified images count toward five-photo publication; published listings cannot lose validity through edit/deletion. Unlist before reducing below five. Drafts can be incomplete. Version conflicts preserve local edits and require an explicit recovery; no blind overwrite.

Custom-rule screening is a small documented denylist for this demo, not comprehensive moderation. No public listing hard-delete exists. Object storage and Postgres are not one transaction: final-object failures never claim attachment; failed deletes/orphaned writes are handled by scoped cleanup. `make storage-cleanup` is dry-run by default. Review output before invoking `docker compose exec -T api uv run --frozen python -m app.storage_cleanup --apply`; it is restricted to expired staging/unreferenced final objects with a retention buffer and preserves referenced images. No bucket-wide destructive reset is part of setup or checks.

The local storage image is RustFS1.0.3-glibc, pinned by digest in Compose. Official [Docker instructions](https://docs.rustfs.com/en/installation/container/docker) and [Boto3 presigning guide](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html) were checked. This is a single-node local S3-compatible setup; AWS API parity, multi-node durability and remote security have not been claimed. Five-minute authorized image URLs are bearer capabilities until expiry. Credentials currently manage only the local demo service; deployment least-privilege IAM is deferred.

## Backend responsibility and transaction map (M2.1)

See [backend architecture](backend/architecture.md) for service entrypoints, transaction/session usage and refresh/photo failure semantics. `auth_routes.py` and `listing_routes.py` adapt HTTP; `auth_service.py` and `listing_service.py` own complete operations and transactions. Call services with an idle SQLAlchemy Session and verified identity values; they recheck live session/account/role/ownership. A caller's existing transaction is rejected rather than silently committed, rolled back or nested. Refresh reuse commits revocation before its failure becomes HTTP401. Cookies are set/cleared by the adapter after service completion. Database-authoritative photo removal and immutable final-image storage remain unchanged. [M2.1 verification](docs/m2-1-evidence.md) records contract/data compatibility and actual regression results.


## Milestone 3 — calendar, discovery and quotes

After normal setup/account provisioning, run:

```sh
make seed-content
make seed-content
make smoke-discovery
```

`seed-content` is explicit and separate from `seed-demo` and test fixtures. Five bounded real interior photographs are checked in under `demo/assets`; six fictional stays reuse them with different cover order. See [asset provenance and license](demo/ATTRIBUTION.md) and the [machine-readable manifest](demo/assets/manifest.json). The photos illustrate interiors; they do not depict the stated fictional properties or verify their locations. `make download-demo-assets` retries missing local source files using recorded HTTPS URLs and SHA256 checks. Compose mounts the assets read-only at `/demo-content`; `DEMO_CONTENT_MANIFEST` is server-only configuration.

The importer authenticates the configured demo Host and uses normal draft, upload-intent, byte verification and publication services. Completed import markers preserve listing/photo identities and subsequent host edits, including unlisting. Partial imports resume conservatively; unsafe conflicts are reported rather than reset. No startup seed, bucket reset or data reset occurs. Exact IDs, rerun proof and useful dates appear in [M3 evidence](docs/m3-evidence.md). On 2026-10-30, a useful search is Lisbon, 2026-11-13 through 2026-11-18, two guests. Advance dates as real business time moves forward.

Host Calendar creates/removes exclusive `[check-in, checkout)` blocks; adjacent blocks are permitted. Public results retain destination/dates/guests in the URL and show server totals when dates are selected. A five-night Lisbon loft quote is €640 nights + €35 cleaning + €94.50 service fee = €769.50. Quotes are signed for ten business minutes and do not reserve availability or charge money. Request stays need at least 24 hours before local scheduled check-in. Auth still uses independent real UTC time.

Public detail omits exact addresses, contact details and management fields. Public images come from verified private-storage copies with five-minute signed GET URLs included in list/detail responses; expiry errors trigger bounded batch renewal. Already issued URLs remain valid until expiry, including after unlisting. Signed URLs contain opaque storage locators as required by S3, but no separate raw-key field is exposed. Search uses UUID keyset pagination; a page filtered by local lead-time/DST rules can be empty with a continuation cursor, which the UI allows users to continue loading.

The additive migration `0003_calendar_demo` introduces calendar occupancy and demo import tracking only. See [M3 API/schema contract](docs/m3-contract.md), [backend transaction map](backend/architecture.md) and [actual M3 verification](docs/m3-evidence.md). That M3 checkpoint did not implement booking/payment; M4 extends it as documented below.


## Milestone 4 — booking and simulated payment

M3 including the timestamp/date-picker correction passed master review before M4. [M4 exact contract](docs/m4-contract.md) defines API schemas, party authorization, immutable snapshots, idempotency and transaction/lock ordering. [M4 handoff](docs/milestone-4-worker.md) is the scope authority; actual verification will be recorded in [M4 evidence](docs/m4-evidence.md).

Reserve on a priced public stay opens checkout and does not hold dates. Sign-in retains the selected listing/dates/guests and obtains a fresh quote. Checkout reviews trip details, rules, policy and server EUR totals; Pay is explicitly simulated, with no card/provider data. Pay creates the reservation, one charge, occupancy and events atomically. Instant stays confirm immediately; request stays are charged and pending until the owning Host accepts or declines. Pending requests hold nights. Decline or unanswered expiry refunds the entire charge including guest fee/cleaning once, releases dates and zeros host/platform entitlement. Normal host fee/entitlement is recorded for later M5; no payout is released.

Instant scheduled check-in must be strictly after business now; request scheduled check-in must be at least24 elapsed hours ahead. Quote expiry/eligibility uses business time and auth/security expiry remains real UTC. Checkout does not silently change a quoted amount: expired/stale terms require a fresh price review.

Guest Trips and reservation detail display the real code/state, booked listing/rules/policy/price snapshot and charge/refund record. These survive host edits/unlisting. Party-authorized photos can be renewed after unlisting, while public endpoints remain published-only; later photo deletion can remove images but not the booked text/terms. Host Today lists pending deadlines and confirmed upcoming stays with accept/decline; hosting/checkouts and cancelled/past lifecycle actions are not invented. Host Calendar distinguishes Pending/Confirmed reservations from removable blocks.

Unknown Pay outcomes retain the original actor/key/quote submission in same-tab sessionStorage and resolve it before issuing a new submission. No access/refresh credentials enter browser storage. Reload preserves recovery context; success or account change clears it. The same key/payload replays the original success even after quote expiry; key reuse with changed input returns409. Keep the tab to recover interrupted checkout; closing its browsing session may discard sessionStorage. A401 requires sign-in to the same account before continuing recovery.

```sh
make dev-up
make migrate
make lint
make format-check
make typecheck
make test
make build
make smoke-auth
make smoke-listings
make smoke-discovery
make smoke-booking
make expire-requests
make persistence-booking
```

The `expiry-worker` local Compose service runs `python -m app.expire_requests --loop --interval 60 --batch-size 100` against the same persistent database. `make expire-requests` runs one bounded batch on demand. Requests expire at business now>=created_at+24h; an overdue host action commits expiry/refund/release before returning409 even if the periodic worker has not run. Repeated/overlapping sweeps are safe. Initial startup can precede migrations; the worker retries while schema/services are unavailable. No clock advance endpoint/UI is included. Isolated injected-time backend tests prove the24h boundary without changing development records or waiting interactively.

`make persistence-booking` creates unique review accounts and one fictional listing with five existing licensed illustrative photos, makes three reservations, accepts/declines as appropriate, edits/unlists only its own listing, and verifies party snapshots/photos and all reservation/money/occupancy/event rows across ordinary db/storage/API/frontend/worker restarts. It retains its review records, never deletes volumes/data/uploads, and writes safe codes/amounts/row evidence under `evidence/m4/`.

M4 does not implement guest/host cancellation, percentage refunds, checked-in/completed transitions, payout release/earnings, admin event-log UI, demo clock controls, real payments, AWS deployment, messaging or email. No new public/private-photo shortcut, dependency migration or destructive reset is required.

## Milestone 5 local review environment

M5 is authorized after M4/global test-isolation review. Exact cancellation, partial-refund migration, payout, clock and API behavior is defined in [M5 contract](docs/m5-contract.md); current verification is recorded in [M5 evidence](docs/m5-evidence.md). No remote deployment or subsequent milestone is authorized.

A separate persisted review project avoids advancing the shared development clock:

```sh
make review-up
make review-migrate
make review-seed
make smoke-cancellation-payout
make persistence-financial
```

Review frontend is [localhost:5183](http://localhost:5183), API8010 and private storage9010. `compose.m5-review.yaml` overrides ports, enables DEMO_MODE and selects separate buckets. The Compose project `stayhub-m5-review` supplies separate named Postgres/object volumes; no data is reset between invocations. Compose must support `!override` (2.24.4+). Review seeds use existing private `.env` seed credentials, never output them. The main development stack remains [localhost:5173](http://localhost:5173) with `DEMO_MODE=false` unless explicitly opted in. Do not use review clock controls on the main stack. Both stacks run locally; no AWS resource is touched.

Main runtime checks:

```sh
make dev-up
make migrate
make lint
make format-check
make typecheck
make test
make build
make smoke-auth
make smoke-listings
make smoke-discovery
make smoke-booking
make sweep
```

`make sweep` runs a bounded unified expiry/check-in/completion/payout batch; the existing expiry-worker service now invokes that unified module every60seconds. `make expire-requests` remains a compatibility entrypoint. Each reservation progresses in chronological scheduled-time order through all due steps, including payout after a one-night stay has completed. Repeated/overlapping runs cannot duplicate simulated releases. GET endpoints do not mutate lifecycle state.

Guest cancellation first reviews exact server policy/refund components, then explicitly confirms. A0% night-policy refund still returns cleaning. Hosts cancel only their own confirmed future stays with a reason/full-refund confirmation; pending requests use Decline. All decisions use booked policy DATA/version and immutable money/rules/schedules, not current listing labels. Original charge/host fee remain history; effective cancellation fee and retained earnings are separate. Full refunds cancel payable entitlement, partial retained entitlement remains due at original check-in+24hours. No bank/card/payment provider, payout clawback or in-stay cancellation.

Host Earnings shows server aggregates across all records and paginated payout rows, with retained cancellation earnings labelled. Trips/Today/calendar show true lifecycle states. Admin `/admin` provides read-only paginated events and separated demo controls: a positive bounded global forward advance requires confirmation and an idempotency key, commits once, then separately attempts a bounded sweep with honest deferred/progress counts. A retry/sweep resumes work without advancing twice. No reset/backward/state-override tools exist.

The persisted database clock offset affects booking/date-picker eligibility, quotes, requests, refund policy and lifecycle/payouts. Public `/api/v1/business-time` returns only time; browser pickers anchor server time plus elapsed monotonic time and refresh on navigation/quote errors/advance. Auth/access/refresh expiry, S3 capabilities, rate limits and event recording time remain real UTC. Advancing business days cannot extend or expire authentication. All backend pytest files retain central fail-closed test database/storage isolation; run suites sharing those resources serially.

`make persistence-financial` is deliberately fixed to the separate review project. It creates unique review records, verifies reference full/50%/0% refunds, retained earnings, one-night completion/payout, duplicate advance once, pre-jump auth validity and persisted clock/financial equality across ordinary service restarts. It retains history and never resets/backdates a clock or deletes volumes. Safe evidence is written under `evidence/m5/`; review credentials and confirmation/quote tokens are never archived.

## M6 local V1 review

Run the ten required checks serially: `make lint`, `make format-check`, `make typecheck`, `make test`, `make build`, `make smoke-auth`, `make smoke-listings`, `make smoke-discovery`, `make smoke-booking`, then `make smoke-cancellation-payout`. Prepare the separate persisted review stack first with `make review-up`, `make review-migrate`, `make review-seed`; the final smoke target is fixed to localhost5183. Never advance the main localhost5173 clock or remove either stack's volumes. Browser checks create additional fictional records and retain them.

For the added real loading/error/retry, role/session and payout-colour checks, run `cd frontend` followed by `npx playwright test e2e/v1-review.spec.ts`. Run Playwright from that directory so it reads the existing configuration. No extra dependencies are required. Backend tests retain globally enforced fail-closed test storage and the separate Postgres test database, including individual-file runs.

Follow the [five-minute local demonstration](docs/m6-demo.md). Main and review setup/migrations/seeds, actual financial reconciliation/restart results, baseline data/photo preservation and desktop/narrow captures are linked from the M6 evidence. Local verification does not establish remote deployment acceptance.

## Integrated Guest/Host release

Guest detail includes an all-photo viewer (arrows, Home/End, Escape and focus
return), a visible listing-local availability calendar, explicit date application,
and server-validated quotes/Reserve. Unavailable calendar cells describe nights;
a guest may check out on the first unavailable night. Availability is advisory
until booking succeeds. Tablet detail stacks the quote and content at 1100px and
below; mobile controls and dialogs remain usable independently of map loading.
Host Today identifies confirmed arrivals for each stay's local business date
from the loaded reservations, with honest pagination counts. Trip cards use
party-authorized stay photos with bounded renewal/retry and booked summaries.

M8 filter fields are additive read-only search parameters. M9A adds migration
`0007_listing_location` after `0006_listing_categories`: nullable paired finite
owner latitude/longitude and a persisted provider budget, without address
backfill or changes to publication requirements, timezones or booked money.
Existing owner PATCH `/api/v1/host/listings/{id}` uses the existing optimistic
version. An address change without explicitly reconfirmed coordinates clears
the old location; both-null coordinates deliberately remove it.

POST `/api/v1/host/location/autocomplete` accepts a bounded JSON query for live
hosts only. The optional key is server-only; see the [operator configuration](infra/README.md#optional-server-only-address-autocomplete).
GET `/api/v1/listings/{id}/location` is published-only and exposes null or a
server-rounded 0.01-degree approximate point, an 800m display area and zoom cap12.
Precise coordinates remain owner-only. This coarse display is not an anonymity
guarantee. No viewport search or exact-location guest release is introduced.
MapLibre/OpenFreeMap assets load lazily, with visible attribution and fallback;
provider failure leaves the listing, manual location controls and booking usable.

Reusable browser tests include `detail-extras.spec.ts`,
`integrated-layout.spec.ts`, date/filter/focus and location specs under
`frontend/e2e`. Run serially with the normal Playwright configuration against an
isolated seeded stack and private `SEED_*` environment values. Tests create
fictional local records. Local runners, screenshots and milestone stack files
are ignored; preserve all review volumes. Mocked autocomplete tests never prove
live Geoapify integration. No production release is implied by local checks.
