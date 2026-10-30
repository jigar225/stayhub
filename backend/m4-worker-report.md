# M4 backend ready-for-coordinator verification

Implemented the exact `docs/m4-contract.md` backend surface. No M5 or AWS work.

## Files and architecture

- New `app/booking_schemas.py`, `booking_quotes.py`, `booking_ledger.py`, `booking_service.py`, `booking_queries.py`, `booking_routes.py`, `expire_requests.py`.
- `models.py` and additive `alembic/versions/0004_bookings.py`: reservations, payments, full refunds, idempotency records and event log; actual reservation occupancy FK/uniqueness while retaining the existing GiST exclusion. Frozen readable PostgreSQL DDL; no reset or data rewrite.
- `calendar_service.py` / `discovery_schemas.py`: block/reservation discriminated occupancy with true pending/confirmed state; Unblock remains block-only.
- `date_rules.py` / `pricing.py`: optional internal `as_of` supports one coherent locked decision clock; quote issuance captures one timestamp. Existing date/DST/pricing behavior retained.
- `main.py` / `auth_routes.py` / `auth_service.py`: compose new router and replace/remove obsolete Today probe while retaining all live-session checks.
- `tests/test_booking.py`: 41 M4 PostgreSQL scenarios; `tests/conftest.py` includes new tables in isolated database truncation. Existing tests retained.
- `architecture.md`: transaction boundaries, locks, clocks, replay and storage authorization documented.

HTTP adapters contain no SQL/transaction orchestration. Complete services require an idle Session. Transaction-scoped quote, ledger and read helpers are separated. Lock order is live identity reads → per-operation advisory try-lock → listing row → reservation row → occupancy/money/events. Expiry scans a bounded page then processes each request in its own listing/reservation transaction. Host expiry rejection is a CommittedFailure value translated to409 only after commit.

## Verification actually run

- `uv run --frozen ruff check app tests alembic`: passed.
- `uv run --frozen ruff format app tests alembic`: 45 files unchanged in final invocation.
- `uv run --frozen mypy app tests`: passed, 40 source files.
- `uv run --frozen pytest tests/test_booking.py -q`: 41 passed, 2 existing warnings, 31.31s.
- `uv run --frozen pytest -q`: **102 passed**, 2 existing warnings, **40.41s** (61 existing +41 M4).

Tests cover exact financial snapshots (76950 charge,2025 fee,65475 host entitlement), instant/request distinction, immutable booked listing/rules/policy DATA and authorized unlisted photo reads; overlapping guest/book/block races and adjacency; advisory same-key contention/retry/replay, changed payload, different actor and expired/terminal quote replay; quote signature/algorithm/issuer/audience/purpose/schema/business time, quote-as-access rejection, own listing/Admin/revoked role, Origin/extra fields; instant before/equal/after and request24h/under in Asia/Kolkata at Pay; malformed/past/reversed/capacity revalidation without money/events; accept/decline/expiry/duplicate-sweep races, exact microsecond deadline and bounded repeated sweep, full refund/reopened dates/system identity; state/payment/refund/occupancy/events/idempotency rollback after flushed writes; DB charge/refund/occupancy reference constraints; pagination and party ownership.

Existing Starlette/httpx and Alembic path_separator deprecation warnings remain. No dependency changes or suppressed assertions.

## Storage isolation correction

The first targeted27-case run omitted importing the existing autouse `isolated_storage` fixture. The database remained isolated, but generated PNG fixture uploads entered development object storage. This was identified and corrected before the expanded41-case and full102-case runs.

`evidence/m4-storage-cleanup.json` records successful narrowly proven cleanup: exactly270 generated objects (135 staging/135 final across27 test listing groups), only within2026-10-30T10:32:26–10:32:42UTC, exact generated PNG/stripped image SHA256 verified, absent from both development/test photo references and listing IDs. All checks completed before any deletion. Zero referenced objects or existing-listing objects deleted; zero objects remain in that exact window. No development database rows were changed. No unrelated object was selected by age/orphan status alone.

## Limits / coordinator work

Backend ready for rebuilt-runtime integration, required root commands, browser/visual review, existing-data/API preservation, ledger reconciliation and restart verification. Those are coordinator evidence, not claimed by this worker's unit/integration run. New M4 full-refund DB constraint deliberately allows only the original full charge; M5 policy refunds need a deliberate later migration. Currently verified party photos may disappear after owner photo deletion; booked text/financial/rule/policy snapshots remain immutable, as contracted. No actual payout is scheduled/released, no cancellation/lifecycle progression/clock controls/event UI is implemented.
