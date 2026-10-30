import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import OrderedDict
from typing import cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request, Response

from app.config import get_settings
from app.errors import ApiError
from app.models import AuthSession, User
from app.schemas import Role, UserOutput

COOKIE = "stayhub_refresh"
COOKIE_PATH = "/api/v1/auth"
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def user_output(user: User) -> UserOutput:
    return UserOutput(
        id=user.id,
        name=user.name,
        email=user.email,
        roles=[cast(Role, row.role) for row in user.memberships],
    )


def require_origin(request: Request) -> None:
    if request.headers.get("origin") not in get_settings().origins:
        raise ApiError(403, "origin_rejected", "This request origin is not allowed.")


def require_json(request: Request) -> None:
    require_origin(request)
    if (
        request.headers.get("content-type", "").split(";")[0].lower()
        != "application/json"
    ):
        raise ApiError(415, "json_required", "Use application/json.")


def csrf_value(session: AuthSession) -> str:
    return hmac.new(
        get_settings().jwt_secret.get_secret_value().encode(),
        f"csrf:{session.id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def set_cookie(response: Response, value: str, expires_in: int) -> None:
    response.set_cookie(
        COOKIE,
        value,
        max_age=max(expires_in, 0),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )


def require_role(user: User, role: str) -> None:
    if role not in {membership.role for membership in user.memberships}:
        raise ApiError(
            403, "forbidden", "Your account does not have access to this page."
        )


class RateLimiter:
    """Bounded, single-process local limiter. No proxy headers are trusted."""

    def __init__(self) -> None:
        self.buckets: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        settings = get_settings()
        current = time.monotonic()
        with self.lock:
            start, count = self.buckets.get(key, (current, 0))
            if current - start >= settings.rate_limit_window_seconds:
                start, count = current, 0
            if count >= settings.rate_limit_attempts:
                retry = math.ceil(
                    settings.rate_limit_window_seconds - (current - start)
                )
                raise ApiError(
                    429,
                    "rate_limited",
                    "Too many attempts. Try again shortly.",
                    {"Retry-After": str(max(1, retry))},
                )
            self.buckets[key] = start, count + 1
            self.buckets.move_to_end(key)
            while len(self.buckets) > 10000:
                self.buckets.popitem(last=False)


limiter = RateLimiter()


def check_csrf(supplied: str, expected_hash: str) -> None:
    """Compare a supplied HTTP header value against a lock-bound session hash."""
    if not supplied or not hmac.compare_digest(digest(supplied), expected_hash):
        raise ApiError(403, "csrf_rejected", "Refresh the page and try again.")
