from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    demo_mode: bool = False
    database_url: str
    jwt_secret: SecretStr
    trusted_origins: str = "http://localhost:5173"
    cookie_secure: bool = False
    jwt_issuer: str = "stayhub"
    jwt_audience: str = "stayhub-web"
    rate_limit_attempts: int = Field(default=10, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)

    s3_use_iam_role: bool = False
    s3_endpoint_url: str = "http://storage:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "stayhub"
    s3_region: str = "us-east-1"
    test_s3_bucket: str = "stayhub-test"

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_origins(self) -> Settings:
        if not self.origins:
            raise ValueError("At least one trusted origin is required")
        for origin in self.origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError(
                    "Trusted origins must be exact HTTP origins without paths"
                )
            if not self.cookie_secure and (
                parsed.scheme != "http"
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError(
                    "COOKIE_SECURE=false is allowed only for local HTTP origins"
                )
        return self

    @property
    def origins(self) -> set[str]:
        return {
            value.strip() for value in self.trusted_origins.split(",") if value.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
