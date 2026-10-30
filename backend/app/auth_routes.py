from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app import auth_service
from app.db import get_db
from app.errors import ApiError
from app.schemas import (
    AuthResponse,
    CsrfResponse,
    LoginInput,
    RegisterInput,
    UserResponse,
)
from app.security import (
    COOKIE,
    clear_cookie,
    limiter,
    require_json,
    require_origin,
    set_cookie,
)

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]


def auth_attempt(request: Request) -> None:
    require_json(request)
    address = request.client.host if request.client else "unknown"
    limiter.check(f"{request.url.path}:{address}")


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(auth_attempt)],
)
def register(body: RegisterInput, db: DB) -> UserResponse:
    return auth_service.register(db, body)


@router.post(
    "/auth/login", response_model=AuthResponse, dependencies=[Depends(auth_attempt)]
)
def login(
    body: LoginInput, request: Request, response: Response, db: DB
) -> AuthResponse:
    result = auth_service.login(db, body)
    set_cookie(response, result.refresh_token, result.refresh_expires_in)
    return result.body


@router.get("/auth/csrf", response_model=CsrfResponse)
def csrf(request: Request, db: DB) -> CsrfResponse:
    # Same-origin browser GET normally omits Origin. Keep the existing SOP and
    # Fetch Metadata guard; session/CSRF lifecycle belongs to the service.
    if request.headers.get("origin") is not None:
        require_origin(request)
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise ApiError(403, "origin_rejected", "This request origin is not allowed.")
    return auth_service.bootstrap_csrf(db, request.cookies.get(COOKIE))


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh(request: Request, response: Response, db: DB) -> AuthResponse:
    require_origin(request)
    result = auth_service.refresh(
        db, request.cookies.get(COOKIE), request.headers.get("x-csrf-token", "")
    )
    if isinstance(result, auth_service.RefreshFailure):
        raise ApiError(401, result.code, result.message)
    set_cookie(response, result.refresh_token, result.refresh_expires_in)
    return result.body


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB) -> None:
    require_origin(request)
    auth_service.logout(
        db, request.cookies.get(COOKIE), request.headers.get("x-csrf-token", "")
    )
    clear_cookie(response)


@router.get("/auth/me", response_model=UserResponse)
def me(request: Request, db: DB) -> UserResponse:
    return auth_service.profile(
        db, auth_service.access_context(request.headers.get("authorization", ""))
    )


@router.post("/me/host-role", response_model=UserResponse)
def host_role(request: Request, db: DB) -> UserResponse:
    actor = auth_service.access_context(request.headers.get("authorization", ""))

    def check_transport() -> None:
        require_origin(request)
        if body_present(request):
            raise ApiError(422, "validation_error", "This operation accepts no fields.")

    return auth_service.enroll_host(db, actor, guard=check_transport)


def body_present(request: Request) -> bool:
    return (
        request.headers.get("content-length", "0") != "0"
        or "transfer-encoding" in request.headers
    )


@router.get("/admin/status", response_model=UserResponse)
def admin_status(request: Request, db: DB) -> UserResponse:
    return auth_service.admin_status(
        db, auth_service.access_context(request.headers.get("authorization", ""))
    )
