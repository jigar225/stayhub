import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import AuthSession, RefreshToken, User, UserRole, now
from app.security import COOKIE, COOKIE_PATH

PASSWORD = "isolated-test-password!"


def signup(client: TestClient, email: str = "guest@example.com") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Guest", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def login(client: TestClient, email: str = "guest@example.com") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def bearer(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


def test_register_login_own_profile_host_additive_logout(client: TestClient) -> None:
    user = signup(client, "GUEST@example.com")["user"]
    assert user["email"] == "guest@example.com"
    assert user["roles"] == ["guest"]
    assert set(user) == {"id", "name", "email", "roles"}
    auth = login(client)
    assert auth["expires_in"] == 900
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).json()["user"] == user
    assert client.get("/api/v1/host/today", headers=bearer(auth)).status_code == 403
    assert client.get("/api/v1/admin/status", headers=bearer(auth)).status_code == 403
    for _ in range(2):
        result = client.post("/api/v1/me/host-role", headers=bearer(auth))
        assert result.status_code == 200
        assert set(result.json()["user"]["roles"]) == {"guest", "host"}
    assert client.get("/api/v1/host/today", headers=bearer(auth)).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]}
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_duplicate_validation_privilege_injection_and_identity(
    client: TestClient,
) -> None:
    first = signup(client)["user"]
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"name": "Other", "email": "Guest@example.com", "password": PASSWORD},
        ).status_code
        == 409
    )
    for field, value in [
        ("roles", ["admin"]),
        ("admin", True),
        ("user_id", first["id"]),
    ]:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Other",
                "email": "other@example.com",
                "password": PASSWORD,
                field: value,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["field_errors"]
        assert PASSWORD not in response.text
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"name": " ", "email": "invalid", "password": "short"},
        ).status_code
        == 422
    )
    auth = login(client)
    assert (
        client.post(
            "/api/v1/me/host-role",
            headers=bearer(auth),
            json={"user_id": first["id"], "roles": ["admin"]},
        ).status_code
        == 422
    )
    second = signup(client, "second@example.com")["user"]
    second_auth = login(client, "second@example.com")
    assert (
        client.get("/api/v1/auth/me", headers=bearer(second_auth)).json()["user"]["id"]
        == second["id"]
    )
    assert first["id"] != second["id"]
    with Session(get_engine()) as db:
        stored = db.get(User, UUID(first["id"]))
        assert stored is not None
        assert stored.password_hash.startswith("$argon2id$")
        assert stored.password_hash != PASSWORD


def test_refresh_rotation_reuse_revokes_session(client: TestClient) -> None:
    signup(client)
    auth = login(client)
    old_cookie = client.cookies.get(COOKIE)
    csrf = client.get("/api/v1/auth/csrf")
    assert csrf.json()["csrf_token"] == auth["csrf_token"]
    result = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": auth["csrf_token"]}
    )
    assert result.status_code == 200
    assert client.cookies.get(COOKIE) != old_cookie
    refreshed = result.json()
    client.cookies.clear()
    client.cookies.set(COOKIE, str(old_cookie), path=COOKIE_PATH)
    reuse = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": auth["csrf_token"]}
    )
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "refresh_reused"
    assert client.get("/api/v1/auth/me", headers=bearer(refreshed)).status_code == 401
    with Session(get_engine()) as db:
        history = list(db.scalars(select(RefreshToken)))
        assert len(history) == 2
        assert all(row.token_hash != old_cookie for row in history)


def test_concurrent_rotation_serializes_and_fails_closed(client: TestClient) -> None:
    signup(client)
    auth = login(client)
    cookie = client.cookies.get(COOKIE)

    def rotate() -> int:
        with TestClient(client.app, base_url="http://localhost:5173") as parallel:
            result = parallel.post(
                "/api/v1/auth/refresh",
                headers={
                    "Origin": "http://localhost:5173",
                    "X-CSRF-Token": auth["csrf_token"],
                    "Cookie": f"{COOKIE}={cookie}",
                },
            ).status_code
            return int(result)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: rotate(), range(2))) == [200, 401]
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).status_code == 401


def test_origin_csrf_json_guards(client: TestClient) -> None:
    signup(client)
    auth = login(client)
    for path in ("login", "register", "refresh", "logout"):
        response = client.post(
            f"/api/v1/auth/{path}",
            headers={"Origin": "https://attacker.example"},
            json={"email": "guest@example.com", "password": PASSWORD, "name": "X"},
        )
        assert response.status_code == 403
    assert client.post("/api/v1/auth/login", content="{}").status_code == 415
    assert (
        client.get(
            "/api/v1/auth/csrf", headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    for path in ("refresh", "logout"):
        assert (
            client.post(
                f"/api/v1/auth/{path}", headers={"X-CSRF-Token": "wrong"}
            ).status_code
            == 403
        )
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).status_code == 200
    cookie_header = client.post(
        "/api/v1/auth/login", json={"email": "guest@example.com", "password": PASSWORD}
    ).headers["set-cookie"]
    assert (
        "HttpOnly" in cookie_header
        and "SameSite=lax" in cookie_header
        and f"Path={COOKIE_PATH}" in cookie_header
    )


def test_invalid_expired_forged_inactive_and_revoked_tokens(client: TestClient) -> None:
    signup(client)
    auth = login(client)
    assert client.get("/api/v1/auth/me").status_code == 401
    settings = get_settings()
    payload = jwt.decode(
        auth["access_token"],
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    variants = [
        {**payload, "exp": int((now() - timedelta(seconds=1)).timestamp())},
        {**payload, "purpose": "refresh"},
        {**payload, "aud": "wrong"},
        {**payload, "iss": "wrong"},
        {**payload, "iat": int((now() + timedelta(minutes=1)).timestamp())},
    ]
    for claims in variants:
        token = jwt.encode(
            claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"
        )
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
    forged = jwt.encode(payload, "wrong" * 12, algorithm="HS256")
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        ).status_code
        == 401
    )
    with Session(get_engine()) as db:
        user = db.get(User, UUID(payload["sub"]))
        assert user
        user.active = False
        db.commit()
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": auth["csrf_token"]}
        ).status_code
        == 401
    )


def test_session_absolute_expiry(client: TestClient) -> None:
    signup(client)
    auth = login(client)
    with Session(get_engine()) as db:
        session = db.scalar(select(AuthSession))
        assert session
        expires = session.expires_at
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": auth["csrf_token"]}
        ).status_code
        == 200
    )
    with Session(get_engine()) as db:
        session = db.scalar(select(AuthSession))
        assert session and session.expires_at == expires
        session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me", headers=bearer(auth)).status_code == 401
    assert client.get("/api/v1/auth/csrf").status_code == 401


def test_admin_exclusive_and_current_roles(client: TestClient) -> None:
    user = signup(client)["user"]
    auth = login(client)
    with Session(get_engine()) as db:
        record = db.get(User, UUID(user["id"]))
        assert record
        db.execute(delete(UserRole).where(UserRole.user_id == record.id))
        db.refresh(record, ["memberships"])
        record.memberships.append(UserRole(role="admin"))
        db.commit()
    assert client.get("/api/v1/admin/status", headers=bearer(auth)).status_code == 200
    assert client.get("/api/v1/host/today", headers=bearer(auth)).status_code == 403
    assert client.post("/api/v1/me/host-role", headers=bearer(auth)).status_code == 403


def test_rate_limit_recovery_real_clock(client: TestClient, monkeypatch: Any) -> None:
    monkeypatch.setenv("RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "1")
    get_settings.cache_clear()
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "missing@example.com", "password": PASSWORD},
            ).status_code
            == 401
        )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": PASSWORD},
    )
    assert response.status_code == 429 and int(response.headers["Retry-After"]) >= 1
    time.sleep(1.05)
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )


def test_provision_creates_roles_and_is_idempotent(tmp_path: Any) -> None:
    from app.provision_users import provision

    manifest = tmp_path / "provision.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [],
                "users": [
                    {
                        "key": "admin",
                        "name": "Platform Admin",
                        "email": "admin-provision@example.com",
                        "roles": ["admin"],
                    },
                    {
                        "key": "host",
                        "name": "Host One",
                        "email": "host-provision@example.com",
                        "roles": ["guest", "host"],
                    },
                ],
            }
        )
    )
    credentials = tmp_path / "creds.txt"
    with Session(get_engine()) as db:
        first = provision(db, manifest, credentials)
    assert first == []
    with Session(get_engine()) as db:
        users = {row.email: row for row in db.scalars(select(User))}
        assert [
            row.role for row in users["admin-provision@example.com"].memberships
        ] == ["admin"]
        assert sorted(
            row.role for row in users["host-provision@example.com"].memberships
        ) == ["guest", "host"]
        original = {email: row.password_hash for email, row in users.items()}
    assert credentials.exists()
    assert "admin-provision@example.com" in credentials.read_text()
    with Session(get_engine()) as db:
        provision(db, manifest, credentials)
    with Session(get_engine()) as db:
        users = {row.email: row for row in db.scalars(select(User))}
        assert {email: row.password_hash for email, row in users.items()} == original


def test_health_errors_no_store_and_oversize(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    response = client.get("/api/v1/auth/me")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    response = client.post("/api/v1/auth/login", content="x" * 17000)
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"


def test_request_limits_and_error_envelope(client: TestClient) -> None:
    malformed = client.post(
        "/api/v1/auth/login", headers={"content-length": "invalid"}, content="{}"
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["request_id"]

    def oversized_chunks() -> Any:
        yield b"x" * 9000
        yield b"x" * 9000

    response = client.post("/api/v1/auth/login", content=oversized_chunks())
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert "error" in response.json()


def test_readiness_fails_safely_when_database_unavailable(
    client: TestClient, monkeypatch: Any
) -> None:
    from sqlalchemy import create_engine

    import app.main as main_module

    unavailable = create_engine(
        "postgresql+psycopg://unavailable@127.0.0.1:1/unavailable",
        connect_args={"connect_timeout": 1},
    )
    monkeypatch.setattr(main_module, "get_engine", lambda: unavailable)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "unavailable@" not in response.text
    unavailable.dispose()


@pytest.mark.parametrize(
    "length,status", [(11, 422), (12, 201), (128, 201), (129, 422)]
)
def test_signup_password_boundaries(
    client: TestClient, length: int, status: int
) -> None:
    password = " " + "x" * (length - 2) + " "
    response = client.post(
        "/api/v1/auth/register",
        json={"name": " Guest ", "email": "boundary@example.com", "password": password},
    )
    assert response.status_code == status
    assert password not in response.text
    if status == 201:
        assert response.json()["user"]["name"] == "Guest"
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "boundary@example.com", "password": password},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "boundary@example.com", "password": password.strip()},
            ).status_code
            == 401
        )
    else:
        assert (
            response.json()["error"]["field_errors"]["password"]
            == "Use 12–128 characters for your password."
        )


@pytest.mark.parametrize("field,value", [("email", "malformed"), ("name", "   ")])
def test_independent_invalid_signup_field(
    client: TestClient, field: str, value: str
) -> None:
    body = {"name": "Guest", "email": "valid@example.com", "password": PASSWORD}
    body[field] = value
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 422
    assert set(response.json()["error"]["field_errors"]) == {field}
    assert PASSWORD not in response.text
    assert "Invalid value." not in response.text


def test_empty_login_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "guest@example.com", "password": ""}
    )
    assert response.status_code == 422
    assert (
        response.json()["error"]["field_errors"]["password"]
        == "Use 1–128 characters for your password."
    )


def test_duplicate_normalized_email(client: TestClient) -> None:
    signup(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Other", "email": " GUEST@EXAMPLE.COM ", "password": PASSWORD},
    )
    assert response.status_code == 409


def test_wrong_credentials_generic(client: TestClient) -> None:
    signup(client)
    for email in ["guest@example.com", "unknown@example.com"]:
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Email or password is incorrect."
        assert response.json()["error"]["field_errors"] is None
        assert "wrong" not in response.text
