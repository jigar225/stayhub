# M2 backend implementation return

Scope: M2 listings and verified private photos only; no discovery, calendar, bookings or money logic. Backend ownership respected. Existing M1 identity/session contract preserved.

## Result and boundaries

- `app/models.py` + Alembic `0002_listings`: owner-linked draft/published/unlisted listings, optimistic version, cancellation-policy FK, nullable draft fields, money/capacity DB checks; explicit photo-intent lifecycle, independent staging/final keys, dimensions/bytes/order and expiry. No hard delete API.
- `app/listing_schemas.py`, `listing_service.py`, `listing_routes.py`: exact `docs/m2-contract.md` endpoints and schemas. Every endpoint checks active session + Host, then own listing (other host404). Origin checks protect mutations. Extra fields/status/owner rejected. Locks serialize listing mutations, photo count, completion and publication. Version409 preserves current data. Published invalid edits rollback. Four verified photos cannot publish; five plus full fields can. Published deletion at five returns409 with unlist-first recovery.
- `app/policies.py` + explicit `app.seed`: four immutable version-one cancellation definitions seeded idempotently, no startup seed and no credential overwrite. M2 stores policy versions only; refunds are deferred.
- `app/storage.py`: Boto3 S3 SigV4/path-style presigned PUT/GET, separate internal/public endpoints; Content-Type+Content-Length signed;5-minute authorization. Actual object bytes and decoded format verified;10MiB source,20million pixels,8192max side. Pixel-only re-encoding strips metadata into an unpredictable independent final key. Missing/mismatched/disguised/expired/oversized source422; storage failure503 without false attached metadata. Completion replay preserves same photo/order/version. SDK timeouts/retries bounded.
- `app.storage_setup`: explicit bucket creation, CORS restricted to trusted frontend origins. No public policy or ACL grants added; existing bucket policy or group ACL is rejected to require privacy review. Dev/test buckets distinct; test must end `-test`.
- `app.storage_cleanup`: dry-run default; `--apply` only expired staging and unreferenced final objects older24h in StayHub-managed prefixes. Listing locks coordinate completion, reference recheck prevents deletion of newly attached objects. Referenced verified photos and buckets preserved; failed deletes counted as backlog. No arbitrary key arguments.
- `app/main.py`: existing auth bodies retain16KiB limit; larger listing JSON bounded64KiB. Safe field error envelope now supports publication-specific fields. No secrets/object keys in API output.

## Runtime/configuration

Existing FastAPI runtime unchanged. Additional env names: S3_ENDPOINT_URL, S3_PUBLIC_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_REGION, TEST_S3_BUCKET. Secrets never returned to clients. Root owns RustFS service/version/persistence/CORS origins and local credentials. Root may run `uv run --frozen python -m app.storage_setup`, explicit `python -m app.seed`, and `python -m app.storage_cleanup --dry-run` (default) or authorized `--apply`.

Exact additional pins: Boto3 1.43.122, botocore 1.43.122, Pillow13.0.0, boto3-stubs1.43.122 (dev typing). Full transitive lock retained. Runtime S3 stub imports are TYPE_CHECKING-only. Existing stack pins unchanged.

Official documentation checked:

- https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html
- https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html
- https://pillow.readthedocs.io/en/stable/reference/Image.html
- Existing M1 FastAPI/SQLAlchemy/Alembic/Pydantic/security references reviewed through current implementation.

## Actual checks and evidence

- Host `backend/.venv/bin/ruff check backend`: exit0, all checks pass; formatter covers25Pythonfiles.
- Workdir backend `.venv/bin/mypy app tests`: exit0 strict,20sourcefiles, S3 operations typed.
- OpenAPI import/generation: exit0,21paths.
- `docker compose build api && docker compose up -d --wait api && docker compose exec -T api uv run --frozen pytest`: exit0,30passed8.03seconds (22M1+8M2), two existing nonfailing Starlette/Alembic warnings. Then strengthened tests with actual oversized source, >20million pixels, changed staging replay, successful JPEG/WebP; final count expected33 and coordinator reruns final source before acceptance.
- Actual RustFS `get_bucket_acl`: only CanonicalUser/FULL_CONTROL, no group grants. Anonymous final object HTTP access denied in real storage test.

`tests/test_listings.py` covers saved draft reload, normalization, pagination, version conflicts, privileged injection, integer money, field bounds, IANA timezone, time validation, unique amenities; Host2/Guest/anonymous isolation on all listing/photo operations;4/5-photo publication gate; invalid published edit rollback; order exact-set validation; published photo-delete guard; unlist preservation; direct HTTP presigned uploads, owner read, anonymous denial; metadata strip; replay+concurrent completion idempotence; expired/missing/disguised/mismatched/oversized/dimension failures; serialized20slot limit; storage503 no attachment and successful retry; scoped cleanup dry-run/apply preserving verified references. Separate test DB/bucket enforced; tests never remove development data.

Root coordinator independently verifies browser flows, screenshots, persistence and root commands. Those outcomes are not claimed by this backend report before coordinator evidence exists. Coordinator already reported HTTP/storage smoke and5image persistence across restart passing; final evidence authority is `docs/m2-evidence.md`.

## Limitations

- Simple custom-rule phrase denylist is a demonstration check, not comprehensive content moderation.
- RustFS is local S3-compatible storage, not proof of AWS compatibility/deployment; no AWS resources created.
- Existing presigned GET authorizations remain valid until their5-minute expiry even if session is revoked/unlisted; no public guest reads in M2.
- Cross-store commit failures may leave unreferenced final objects;24h cleanup handles them conservatively. Storage deletion failure after DB removal is a backlog, not a false photo attachment.
- Security/concurrency boundaries are tested locally. Root final check results are required before marking complete. No M3 work started.
