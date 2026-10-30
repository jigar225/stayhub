from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.auth_routes import router
from app.booking_routes import router as booking_router
from app.calendar_routes import router as calendar_router
from app.config import get_settings
from app.db import get_engine
from app.discovery_routes import router as discovery_router
from app.errors import ApiError, error_response
from app.financial_routes import router as financial_router
from app.listing_routes import router as listing_router

get_settings()  # Fail fast on missing or invalid runtime configuration.
app = FastAPI(title="StayHub API", version="0.2.0")
app.include_router(router)
app.include_router(listing_router)
app.include_router(calendar_router)
app.include_router(discovery_router)
app.include_router(booking_router)
app.include_router(financial_router)


@app.middleware("http")
async def request_metadata(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request.state.request_id = str(uuid4())
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        length = -1
    body_limit = 16384 if request.url.path.startswith("/api/v1/auth") else 65536
    response: Response
    if length < 0:
        response = error_response(
            request, 400, "invalid_request", "Invalid request length."
        )
    elif length > body_limit:
        response = error_response(
            request, 413, "request_too_large", "Request body is too large."
        )
    else:
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > body_limit:
                break
            chunks.append(chunk)
        if size > body_limit:
            response = error_response(
                request, 413, "request_too_large", "Request body is too large."
            )
        else:
            request._body = b"".join(chunks)
            try:
                response = await call_next(request)
            except Exception:
                response = error_response(
                    request,
                    500,
                    "internal_error",
                    "The service could not complete this request.",
                )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/v1"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ApiError)
async def api_error(request: Request, error: ApiError) -> Response:
    return error_response(
        request,
        error.status,
        error.code,
        error.message,
        field_errors=error.field_errors,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError) -> Response:
    fields = {}
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"] if part != "body")
        kind = item["type"]
        message = "Invalid value."
        if field == "email":
            message = "Enter a valid email address (up to 254 characters)."
        elif field == "name":
            message = "Enter your name (1–100 characters, not only spaces)."
        elif field == "password":
            minimum = 12 if request.url.path.endswith("/register") else 1
            message = f"Use {minimum}–128 characters for your password."
        elif kind == "extra_forbidden":
            message = "This field is not allowed."
        fields[field] = message
    return error_response(
        request, 422, "validation_error", "Check the highlighted fields.", fields
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException) -> Response:
    return error_response(
        request, error.status_code, "http_error", "Request could not be completed."
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, error: SQLAlchemyError) -> Response:
    return error_response(
        request,
        503,
        "service_unavailable",
        "The service is temporarily unavailable. Please retry.",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT version_num FROM alembic_version"))
    return {"status": "ready"}
