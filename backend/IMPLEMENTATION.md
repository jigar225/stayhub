# M1 backend notes

The API is a synchronous FastAPI application using SQLAlchemy sessions scoped to each request. PostgreSQL is the authoritative store for users, role memberships, revocable sessions and SHA-256 refresh token history. Argon2id parameters are time_cost=3, memory_cost=65536 KiB, parallelism=4, with random per-password salts. Access JWTs use fixed HS256, configured issuer/audience, required purpose/identity/session/timestamps and a 900-second lifetime. Each protected request checks current account/session/roles in PostgreSQL.

Rotation locks the session row, rereads token consumption after acquiring the lock, consumes the old token and inserts its replacement in one commit. Absolute session lifetime remains seven real days. Reuse revokes the entire session, including previously issued access tokens. Concurrent rotations deliberately fail closed; the client must recover with sign-in. CSRF tokens are HMAC-derived per session with a stored digest. Cookie mutations require an exact trusted Origin and the CSRF header. Signup/login require exact trusted Origin and JSON. Bootstrap GET uses browser same-origin policy (no CORS enabled), rejects cross-origin Origin/Fetch Metadata and never extends sessions.

The single-process local rate limiter counts signup/login attempts per route and direct peer IP with a monotonic clock, fixed window, bounded 10,000-key memory and Retry-After. Proxy forwarding headers are not trusted. It is deliberately not a distributed limiter and needs replacement before multi-instance deployment. Request bodies are bounded at 16 KiB, including streamed bodies. Security expiry always uses real UTC time.

No users are seeded at startup. `python -m app.seed` requires all three explicit seed identities and passwords, creates Guest / Guest+Host / exclusive Admin transactionally, preserves existing credentials, and refuses mismatched roles. Errors never print seed credential values. Test setup refuses any database whose name does not end in `_test`; tests migrate that separate database and truncate only those four auth tables.

## Runtime interface

Working directory is `backend/` locally, `/app` in its image. Commands: `uv sync --frozen`, `uv run --frozen alembic upgrade head`, `uv run --frozen python -m app.seed`, `uv run --frozen uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`. Lint `uv run --frozen ruff check .`; formatting `uv run --frozen ruff format --check .`; static types `uv run --frozen mypy app tests`; tests `uv run --frozen pytest`; build equivalent `uv run --frozen python -c 'from app.main import app; app.openapi()'` validates imports, configuration and executable schemas.

Required configuration names: DATABASE_URL, JWT_SECRET. Optional configuration names: TRUSTED_ORIGINS, COOKIE_SECURE, JWT_ISSUER, JWT_AUDIENCE, RATE_LIMIT_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS. Tests require TEST_DATABASE_URL. Explicit seed uses SEED_GUEST_NAME/EMAIL/PASSWORD, SEED_HOST_NAME/EMAIL/PASSWORD, SEED_ADMIN_NAME/EMAIL/PASSWORD. Never put their values in source or evidence. Insecure cookies are permitted only for local HTTP trusted origins. The API exports `/health` liveness and `/ready` database/schema readiness.

## Official documentation reviewed

- [FastAPI JWT security](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) and [release notes](https://fastapi.tiangolo.com/release-notes/)
- [SQLAlchemy session transaction lifecycle](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) and [2.1 release series](https://docs.sqlalchemy.org/en/21/changelog/changelog_21.html)
- [Alembic migration tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Argon2-cffi PasswordHasher parameters and Argon2id](https://argon2-cffi.readthedocs.io/en/stable/api.html)
- [PyJWT fixed algorithm and claim validation](https://pyjwt.readthedocs.io/en/stable/usage.html)
- [Psycopg3 transaction usage](https://www.psycopg.org/psycopg3/docs/basic/usage.html)
- [Pydantic settings configuration](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

Exact resolved versions and reproducible transitive pins live in `uv.lock`. Availability from the configured registry, runtime checks and that lock take precedence over documentation pages advertising a newer release that the registry cannot supply.
