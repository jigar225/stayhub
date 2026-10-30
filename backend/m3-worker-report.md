# M3 backend return

Scope: persisted Host blocks, published-only public discovery/detail/availability/photos, server integer price quotes and explicit non-destructive licensed-content import. No reservations/payment/calendar-booking workflows, money movement, clock controls or AWS deployment. Backend ownership respected; root owns assets/licensing/config/commands/integration evidence.

## Implementation

- Migration `0003_calendar_demo`: shared `calendar_entries` with listing FK, date ordering and kind/reference checks; btree_gist extension plus active-only GiST exclusion over listing equality and `[check_in,check_out)` daterange overlap. M3 writes blocks only; future M4 reservation occupancy must use this same constraint/table. Removal deactivates history, never hard-deletes it. Demo import markers and asset/photo mappings preserve identities and edits.
- `calendar_service.py` / `calendar_routes.py`: complete owner/Host operations, service-owned idle-Session transactions and M2.1 transport guard ordering. Own calendar reads, block create/remove, per-listing mutation locks and database conflict409. Calendar blocks do not modify listing content version.
- `date_rules.py`: 1–180-night stays/blocks, nonpast listing-local check-in and730-day horizon, 1–93-day bounded calendar reads within prior31/next730 local days. ZoneInfo resolves scheduled local times to UTC; nonexistent DST times rejected, ambiguity uses documented fold0.
- `discovery_service.py`, `discovery_routes.py`, `discovery_schemas.py`: public published-only batch reads and explicit allowlisted DTOs, capacity/literal case-insensitive destination search, UUID keyset pagination, paired date validation, listing-local past filtering and full-range active occupancy exclusion. Summary contains cover URL, detail/batch renewal all verified image URLs; private S3 bucket retained. No address, contact/email, management version/status/owner fields or raw storage-key fields. Signed URLs necessarily carry opaque object locators and remain capability URLs until5-minute expiry.
- `pricing.py`: authoritative integer EUR arithmetic shared by dated discovery and quote. Guest fee `(subtotal*14+50)//100`; five nights12800+3500 yields67500 subtotal,9450fee,76950total. Nights use date differences through DST. Published/current capacity/availability/date/request-lead checks; quotes do not reserve or charge. Signed10-business-minute quote binds version, dates, guests, money, policy and scheduled times with separate audience/purpose from access JWT.
- `business_time.now()` is a small aware-UTC interface returning real time in M3, injectable in tests. Existing auth/session expiry still uses real security time; S3 URLs also use actual security time rather than future business offsets.
- `seed_content.py`: explicit manifest-only importer, no network downloads. Existing SEED_HOST login via auth service; source size/path/checksum validation; SAME listing/draft/upload-intent/photo verification/publication services. Internal trusted creation supports stable UUID5 ID; HTTP create schema remains `{}`. Mappings persisted before upload completion; completed markers preserve all host edits/unlisting/photo changes. Partial missing assets resume, verified identities retained; expired unverified intents can be safely replaced. Unexpected version jumps/ambiguous interruption preserve content and report incomplete, never reset. CLI advisory lock prevents concurrent import commands. Useful +14/+19-day search examples printed with stable listing/photo IDs and sanitized counts.

## Runtime and versions

No dependency/runtime upgrades. Existing PostgreSQL18.6, SQLAlchemy2.1.6, Python3.13/ZoneInfo, FastAPI/S3/Pillow pins unchanged. New env only `DEMO_CONTENT_MANIFEST`; root mounts manifest/assets read-only. Existing S3 and SEED_HOST envs reused. Account/policy seed and content seed remain explicit, separate commands; nothing seeds at application startup.

Official docs checked:

- https://www.postgresql.org/docs/current/rangetypes.html — half-open ranges, btree_gist and exclusion.
- https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#sqlalchemy.dialects.postgresql.ExcludeConstraint — actual SQLAlchemy constraint API.
- https://docs.python.org/3/library/zoneinfo.html — IANA zones, DST and fold handling.

## Verification checkpoint

Backend host Ruff lint/format and strict mypy32sourcefiles passed before coordinator rebuild. Initial coordinator pytest returned48pass/1fail: PostgreSQL may reject a direct concurrent exclusion-index INSERT as a40P01 deadlock victim rather than23P01 exclusion violation. The test now accepts only those two rejection SQLSTATEs while still requiring exactlyone committed transaction and one persisted row. The API race remains serialized and requires201/409. Added horizon regression makes final expected count50; coordinator final run is authoritative. Existing40 Postgres/S3/auth/service regressions retained. Added10 M3 scenarios in `tests/test_discovery.py`: calendar adjacency/overlap/unblock/ownership/version retention; actual concurrent SQL exclusion and API races; date bounds; private/public visibility and field projection; real signed S3 batch reads with unsigned denial; capacity/destination/full-range search/pagination/errors; quote arithmetic/signature/purpose separation; precise71-hour UTC span for3calendar nights across DST plus nonexistent/fold cases; request24h/local-past/auth-clock separation; partial asset import resume and repeated host-edit/unlist preservation; exact listing-local730-day future boundary with UTC fallback when no matching candidates.

Coordinator independently reports first6-listing import with30verified real licensed photos passing; second run6preserved with identical photo IDs. Evidence: `evidence/m3/seed-first.log`, `seed-second.log`. Final pytest/root/browser/persistence compatibility results and screenshot/provenance evidence belong to coordinator `docs/m3-evidence.md`; do not treat this worker checkpoint as final acceptance.

## Stable IDs and importer behavior

IDs are `uuid5(NAMESPACE_URL, 'stayhub:demo:' + demo_key)` for the six root-manifest keys: lisbon-loft-v1, lisbon-courtyard-v1, goa-house-v1, goa-room-v1, kyoto-house-v1, kyoto-room-v1. Root manifest owns exact content/photo provenance. First Lisbon price fixture remains12800nightly/3500cleaning. User-created listings/uploads are never enumerated for deletion or reset.

## Limitations

Local S3 compatibility/HTTP and five-minute signed URL capability limitations remain. Demo photos are licensed illustrations reused explicitly, not proof of actual properties/locations. Search applies request-lead/DST validation to bounded candidate pages while retaining the cursor, so a page may contain fewer than requested items. Ambiguous interrupted import writes deliberately stop rather than adopting possible host edits. No M4 behavior claimed.
