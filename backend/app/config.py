"""
Application configuration using pydantic-settings.
All settings are read from environment variables or .env file.
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "sqlite:///./testpilot.db"

    # Environment
    ENVIRONMENT: str = "development"

    # Security & JWT
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours
    ALLOW_PUBLIC_REGISTRATION: bool = False

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        env = (self.ENVIRONMENT or "").strip().lower()
        secret = (self.SECRET_KEY or "").strip()
        if not secret:
            raise ValueError("SECRET_KEY must not be empty.")

        insecure_keys = {
            "change-me-in-production",
            "secret",
            "password",
            "12345678",
            "change-me",
            "test-secret-key-123",
        }

        if env == "production":
            if secret.lower() in insecure_keys:
                raise ValueError(
                    "Default or insecure SECRET_KEY is not permitted in production. "
                    "Configure a strong, cryptographically random secret."
                )
            if len(secret) < 32:
                raise ValueError(
                    "In production, SECRET_KEY must be at least 32 characters long."
                )
            if len(set(secret)) < 8:
                raise ValueError(
                    "In production, SECRET_KEY must have sufficient entropy (at least 8 distinct characters)."
                )
        elif len(secret) < 8:
            raise ValueError("SECRET_KEY must be at least 8 characters long.")

        return self

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"


    # Artifacts storage
    ARTIFACTS_DIR: str = "./artifacts"

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 10

    # Playwright
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT_MS: int = 30000

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        """Max upload size in bytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
