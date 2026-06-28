"""
Centralized application configuration.

All values are overridable via environment variables / a .env file so the
exact same codebase runs locally (SQLite, mocked SMS/Mpesa) and in
production (PostgreSQL+PostGIS, real Africa's Talking / Daraja credentials)
without code changes -- only configuration changes.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "Kejaflix API"
    ENV: str = "development"  # development | staging | production
    DEBUG: bool = True

    # --- Database ---
    # Local dev defaults to SQLite for zero-setup. In production point this at
    # PostgreSQL with PostGIS, e.g.:
    # postgresql+psycopg2://user:pass@host:5432/kejaflix
    DATABASE_URL: str = "sqlite:///./kejaflix.db"

    # --- Auth / JWT ---
    JWT_SECRET: str = "dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- OTP ---
    OTP_EXPIRE_MINUTES: int = 5
    OTP_LENGTH: int = 6
    # When true, the generated OTP is echoed back in the API response instead
    # of (or in addition to) being sent over SMS. Convenient for local/dev
    # testing without an Africa's Talking account. MUST be false in production.
    OTP_DEBUG_ECHO: bool = True

    # --- SMS provider (Africa's Talking) ---
    AT_USERNAME: str = ""
    AT_API_KEY: str = ""
    AT_SENDER_ID: str = "KEJAFLIX"

    # --- Mpesa Daraja ---
    DARAJA_CONSUMER_KEY: str = ""
    DARAJA_CONSUMER_SECRET: str = ""
    DARAJA_SHORTCODE: str = ""
    DARAJA_PASSKEY: str = ""
    DARAJA_ENV: str = "sandbox"  # sandbox | production
    DARAJA_CALLBACK_BASE_URL: str = "https://api.kejaflix.com"
    # When true, payments are auto-marked successful immediately instead of
    # calling the real Daraja STK Push API. Useful for local dev/tests.
    MPESA_MOCK_MODE: bool = True

    SEARCH_UNLOCK_FEE_KES: int = 250
    FIELD_AGENT_REWARD_KES: int = 500
    FIELD_AGENT_MIN_PAYOUT_KES: int = 500
    FIELD_AGENT_DUPLICATE_RADIUS_M: int = 20
    FIELD_AGENT_GPS_ADDRESS_TOLERANCE_M: int = 50

    # --- Google Maps Platform ---
    GOOGLE_MAPS_API_KEY: str = ""

    # --- File storage ---
    # Local dev writes to ./static. Production should point this at an S3 /
    # GCS bucket -- see app/services/storage.py for the swap-in point.
    MEDIA_ROOT: str = "./static"
    MEDIA_BASE_URL: str = "http://localhost:8000/static"


@lru_cache
def get_settings() -> Settings:
    return Settings()
