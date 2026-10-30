# M2.1 backend refactor return

Scope: backend workflow boundaries and transaction ownership only. No frontend, data model, DB/session dependency, configuration, migration, storage adapter/cleanup/setup, dependency/lock or API schema changes. No M3 work. Coordinator owns final integrated evidence and root documentation.

## Changes

- Replaced generic `app/routes.py` with explicitly named `app/auth_routes.py`. Auth and listing route functions retain their names, paths, schemas, statuses and cookie/origin handling. Handlers now extract/validate HTTP values and invoke one complete service operation; they contain no SQL, commits or partial business workflows.
- Added `app/auth_service.py`: registration, login, bootstrap, rotation/reuse revocation, logout, profile, Host enrollment and role-probe operations. A frozen access context carries verified user/session/expiry values without any DB query before operation start. Every authenticated operation reloads current active session/account/roles and checks both access and session expiry inside its own transaction.
- Expanded `app/listing_service.py` from helper fragments to complete owner listing/photo operations. Version/publication/photo-count/ownership/role checks, row locking, state changes and snapshots belong to those operations. Internal helpers are private and never commit. Existing direct SQLAlchemy structure retained, with no repositories/framework layer.
- `app/security.py` retains pure crypto/password/CSRF/hash/role helpers and small HTTP origin/JSON/cookie/rate helpers; DB/session workflows moved to auth service. CSRF header extraction stays in auth routes; its pure value/hash comparison stays bound to the locked session inside the service.
- `app/main.py` imports the renamed auth router. Existing Pydantic schemas are unchanged; service result dataclasses are internal and never appear as API response models.
- `backend/architecture.md` documents boundaries, idle Session contract, transactions, refresh failure outcome and unchanged cross-store cleanup semantics.

## Transaction guarantees

Each public operation uses `with db.begin()` on a caller-supplied idle Session. No helper silently commits/rolls back existing caller work and no nested/savepoint transaction workaround exists. Existing caller transactions are rejected explicitly by SQLAlchemy. All result snapshots are built after required flushes and before commit; returning snapshots never causes lazy ORM access/autobegin after commit. Locked listing/session and login/current-user reads refresh retained identity-map state, including callers reusing `expire_on_commit=False` sessions.

Refresh rotation consumes old history and creates its replacement atomically under the session lock. Reuse/inactive-account revocation returns `RefreshFailure` after the transaction commits. The HTTP adapter then renders401. It cannot accidentally roll back security revocation by raising its HTTP error inside the transaction. Refresh cookie values are returned as internal domain values and written to the response only after a successful commit.

Photo completion still writes a separate final object while holding the listing lock, then commits verified metadata; failed commit leaves only a cleanup orphan. Deletion commits authoritative DB removal before external best-effort deletes. Storage adapters, immutable final keys, idempotent retry ordering and cleanup grace period remain unchanged.

## Verification performed by backend worker

- Exact OpenAPI object equality against coordinator `evidence/m2-1/openapi-before.json`: true after moving services/routes; handler/default operation IDs unchanged.
- Host `backend/.venv/bin/ruff check backend`: exit0.
- Host `backend/.venv/bin/ruff format --check backend`: exit0 (28 Python files in last output).
- Workdir backend `.venv/bin/mypy app tests`: exit0 strict,22 source files.

All33 existing real PostgreSQL/S3 tests are retained unchanged. Added `tests/test_services.py` with five focused direct-service Postgres cases (no HTTP Request/Response): independently visible reuse revocation before failure translation; CSRF failure rollback/logout/access expiry; complete listing owner/role/version/publication checks; rejection of caller active transactions without commit/rollback of caller writes; retained ORM state refreshed after concurrent listing update/session revocation. Two focused HTTP regressions preserve mixed-invalid-request precedence (revoked identity401 before Origin/body, other owner404 before Origin, wrong role403). Optional adapter-supplied pure guards run after live permissions at the original position; no HTTP types enter services. Final integrated count expected40. Coordinator runs final rebuilt image/tests/browser journeys and records actual outcomes; those results supersede this worker's host-only checkpoint.

No required compatibility exception or schema change identified. Existing warning/limitations, local storage semantics and auth policy remain as before.
