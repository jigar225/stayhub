from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        field_errors: dict[str, str] | None = None,
    ):
        self.field_errors = field_errors
        self.status, self.code, self.message, self.headers = (
            status,
            code,
            message,
            headers,
        )


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    field_errors: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors,
                "request_id": request.state.request_id,
            }
        },
        headers=headers,
    )
