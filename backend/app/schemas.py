from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["guest", "host", "admin"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(StrictModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegisterInput(LoginInput):
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class UserOutput(BaseModel):
    id: UUID
    name: str
    email: str
    roles: list[Role]


class UserResponse(BaseModel):
    user: UserOutput


class AuthResponse(UserResponse):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: Literal[900] = 900
    csrf_token: str


class CsrfResponse(BaseModel):
    csrf_token: str


class HostTodayResponse(BaseModel):
    status: Literal["not_available"] = "not_available"
    message: str = "Hosting operations arrive in a later milestone."
