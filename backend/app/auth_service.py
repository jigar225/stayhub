"""Complete account/session operations with explicit SQLAlchemy transactions.

Inputs are validated value objects, never HTTP Request/Response. Callers provide
an idle Session; every operation owns begin/commit/rollback and returns snapshots.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import AuthSession, RefreshToken, User, UserRole, now
from app.schemas import (
    AuthResponse,
    CsrfResponse,
    LoginInput,
    RegisterInput,
    UserResponse,
)
from app.security import (
    DUMMY_HASH,
    check_csrf,
    csrf_value,
    digest,
    password_hasher,
    require_role,
    user_output,
    verify_password,
)


@dataclass(frozen=True)
class AccessContext:
    user_id: UUID
    session_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class AuthIssue:
    body: AuthResponse
    refresh_token: str
    refresh_expires_in: int


@dataclass(frozen=True)
class RefreshFailure:
    """An authentication failure returned only after required revocation commits."""

    code: str
    message: str


def access_context(authorization: str) -> AccessContext:
    """Verify the token without a DB read/autobegin; operations check live state."""
    if not authorization.startswith("Bearer "):
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            authorization[7:],
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "sid", "iat", "exp", "iss", "aud", "purpose"]},
        )
        if claims["purpose"] != "access":
            raise ValueError("purpose")
        return AccessContext(
            UUID(claims["sub"]),
            UUID(claims["sid"]),
            datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (
        jwt.InvalidTokenError,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
    ):
        raise ApiError(
            401, "unauthenticated", "Your session has expired. Sign in again."
        ) from None


def current_user(db: Session, actor: AccessContext, role: str | None = None) -> User:
    """Called inside an operation's transaction; always read current DB roles."""
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == actor.session_id)
        .execution_options(populate_existing=True)
    )
    user = db.scalar(
        select(User)
        .where(User.id == actor.user_id)
        .execution_options(populate_existing=True)
    )
    if (
        not session
        or session.user_id != actor.user_id
        or session.revoked_at
        or session.expires_at <= now()
        or actor.expires_at <= now()
        or not user
        or not user.active
    ):
        raise ApiError(
            401, "unauthenticated", "Your session has expired. Sign in again."
        )
    if role is not None:
        require_role(user, role)
    return user


def register(db: Session, body: RegisterInput) -> UserResponse:
    try:
        with db.begin():
            user = User(
                email=str(body.email),
                name=body.name,
                password_hash=password_hasher.hash(body.password),
                memberships=[UserRole(role="guest")],
            )
            db.add(user)
            db.flush()
            result = UserResponse(user=user_output(user))
        return result
    except IntegrityError:
        raise ApiError(
            409, "email_exists", "An account with this email already exists."
        ) from None


def _issue_auth(db: Session, user: User, session: AuthSession) -> AuthIssue:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            session_id=session.id,
            token_hash=digest(token),
            expires_at=session.expires_at,
        )
    )
    issued = now()
    encoded = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(session.id),
            "iat": issued,
            "exp": issued + timedelta(minutes=15),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "purpose": "access",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return AuthIssue(
        AuthResponse(
            user=user_output(user), access_token=encoded, csrf_token=csrf_value(session)
        ),
        token,
        int((session.expires_at - issued).total_seconds()),
    )


def login(db: Session, body: LoginInput) -> AuthIssue:
    with db.begin():
        user = db.scalar(
            select(User)
            .where(User.email == str(body.email))
            .execution_options(populate_existing=True)
        )
        valid = verify_password(
            user.password_hash if user else DUMMY_HASH, body.password
        )
        if not user or not valid or not user.active:
            raise ApiError(
                401, "invalid_credentials", "Email or password is incorrect."
            )
        session = AuthSession(
            id=uuid4(),
            user_id=user.id,
            expires_at=now() + timedelta(days=7),
            csrf_hash="",
        )
        session.csrf_hash = digest(csrf_value(session))
        db.add(session)
        db.flush()
        result = _issue_auth(db, user, session)
    return result


def _refresh_session(
    db: Session, raw: str | None, lock: bool = False
) -> tuple[AuthSession, RefreshToken] | None:
    if not raw or len(raw) > 256:
        return None
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == digest(raw))
    )
    if token is None:
        return None
    query = (
        select(AuthSession)
        .where(AuthSession.id == token.session_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    # Re-read after session lock: another rotation could have consumed the token
    # while this request waited under PostgreSQL READ COMMITTED isolation.
    db.refresh(token)
    if (
        session is None
        or session.revoked_at
        or session.expires_at <= now()
        or token.expires_at <= now()
    ):
        return None
    return session, token


def bootstrap_csrf(db: Session, refresh_token: str | None) -> CsrfResponse:
    with db.begin():
        found = _refresh_session(db, refresh_token)
        if not found or found[1].consumed_at:
            raise ApiError(401, "unauthenticated", "Sign in to continue.")
        user = db.get(User, found[0].user_id)
        if not user or not user.active:
            raise ApiError(401, "unauthenticated", "Sign in to continue.")
        result = CsrfResponse(csrf_token=csrf_value(found[0]))
    return result


def refresh(
    db: Session, refresh_token: str | None, supplied_csrf: str
) -> AuthIssue | RefreshFailure:
    with db.begin():
        found = _refresh_session(db, refresh_token, lock=True)
        if not found:
            raise ApiError(
                401, "unauthenticated", "Your session has expired. Sign in again."
            )
        session, token = found
        check_csrf(supplied_csrf, session.csrf_hash)
        result: AuthIssue | RefreshFailure
        if token.consumed_at:
            session.revoked_at = now()
            result = RefreshFailure(
                "refresh_reused", "Your session has expired. Sign in again."
            )
        else:
            user = db.get(User, session.user_id)
            if not user or not user.active:
                session.revoked_at = now()
                result = RefreshFailure("unauthenticated", "Sign in to continue.")
            else:
                token.consumed_at = now()
                result = _issue_auth(db, user, session)
    # The outcome reaches HTTP only AFTER begin exits and commits revocation.
    # Raising the 401 inside the transaction would roll that security write back.
    return result


def logout(db: Session, refresh_token: str | None, supplied_csrf: str) -> None:
    with db.begin():
        found = _refresh_session(db, refresh_token, lock=True)
        if found:
            session, _ = found
            check_csrf(supplied_csrf, session.csrf_hash)
            session.revoked_at = now()


def profile(db: Session, actor: AccessContext) -> UserResponse:
    with db.begin():
        result = UserResponse(user=user_output(current_user(db, actor)))
    return result


def enroll_host(
    db: Session, actor: AccessContext, guard: Callable[[], None] | None = None
) -> UserResponse:
    with db.begin():
        user = current_user(db, actor)
        if guard is not None:
            guard()
        db.execute(select(User.id).where(User.id == user.id).with_for_update())
        db.refresh(user, ["memberships"])
        roles = {membership.role for membership in user.memberships}
        if "admin" in roles:
            raise ApiError(403, "forbidden", "Admin accounts cannot enroll as hosts.")
        if "host" not in roles:
            user.memberships.append(UserRole(role="host"))
        db.flush()
        result = UserResponse(user=user_output(user))
    return result


def admin_status(db: Session, actor: AccessContext) -> UserResponse:
    with db.begin():
        result = UserResponse(user=user_output(current_user(db, actor, "admin")))
    return result
