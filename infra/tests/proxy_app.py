"""Isolated proxy test app; real auth dependency/limiter, no database operations."""

from app.auth_routes import auth_attempt
from app.errors import ApiError, error_response
from fastapi import Depends, FastAPI, Request

app = FastAPI()


@app.exception_handler(ApiError)
async def handle(request, error):
    request.state.request_id = "proxy-test"
    return error_response(
        request, error.status, error.code, error.message, headers=error.headers
    )


@app.post("/api/v1/auth/login", dependencies=[Depends(auth_attempt)])
def login(request: Request):
    return {"client": request.client.host, "scheme": request.url.scheme}
