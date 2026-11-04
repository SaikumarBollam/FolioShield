"""
Configuration Management for FolioShield.
Provides strongly-typed, production-ready environment configuration
with seamless switching between 'production', 'testing', and 'development' modes.
"""

import os
from dataclasses import dataclass
from typing import Optional, Literal
from dotenv import load_dotenv

# Automatically load .env file if present
load_dotenv()

EnvironmentMode = Literal["development", "testing", "production"]


@dataclass(frozen=True)
class Settings:
    """
    Centralized, immutable application settings.
    """
    # Environment Selector
    environment: EnvironmentMode

    # AI Model & Provider
    llama_provider: str
    groq_api_key: Optional[str]
    together_api_key: Optional[str]
    openrouter_api_key: Optional[str]
    llama_text_model: Optional[str]
    llama_vision_model: Optional[str]

    # Hotel & Merchant Profile
    merchant_name: str
    hotel_contact_email: str

    # Security & File Limits
    max_upload_size_mb: int
    allowed_extensions: tuple

    # Operational Feature Flags
    enable_test_scenarios: bool
    show_debug_details: bool
    request_timeout_seconds: int

    # Audit & Storage
    log_dir: str
    log_level: str
    exhibit_store_dir: str
    case_db_path: str

    # API protection (Phase 1 P0)
    api_key: Optional[str]
    api_allow_legacy_unauthenticated: bool
    api_rate_limit_per_min: int
    api_host: str

    # API server & integrations (Phase 3 P2: centralized from core/api.py,
    # core/audit_logger.py, core/integrations/secrets.py, app.py)
    api_port: int
    api_max_body_mb: int
    api_cors_origins: tuple
    integration_root: str
    webhook_resume_seconds: int
    webhook_secret_key: Optional[str]
    audit_hmac_key: Optional[str]
    database_url: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    s3_bucket_name: Optional[str] = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        p = provider.lower()
        if p == "groq":
            return self.groq_api_key
        elif p == "together":
            return self.together_api_key
        elif p == "openrouter":
            return self.openrouter_api_key
        return None


def get_settings(env_override: Optional[str] = None) -> Settings:
    """
    Factory to construct and validate Settings from environment variables.
    Supports runtime override for automated testing suites.
    """
    raw_env = (env_override or os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()
    if raw_env in ("prod", "production"):
        env: EnvironmentMode = "production"
    elif raw_env in ("test", "testing"):
        env = "testing"
    else:
        env = "development"

    # Default provider: in testing/dev default to mock, in prod can be groq or mock fallback
    default_provider = "mock" if env in ("testing", "development") else "groq"
    provider = os.getenv("LLAMA_PROVIDER", default_provider).strip().lower()

    # Feature flags based on environment
    # In production, staff should not accidentally run mock scenarios unless explicitly enabled
    default_test_scenarios = (env != "production")
    env_test_scenarios = os.getenv("ENABLE_TEST_SCENARIOS")
    if env_test_scenarios is not None:
        enable_test_scenarios = env_test_scenarios.strip().lower() in ("true", "1", "yes")
    else:
        enable_test_scenarios = default_test_scenarios

    default_debug = (env != "production")
    env_debug = os.getenv("SHOW_DEBUG_DETAILS")
    if env_debug is not None:
        show_debug = env_debug.strip().lower() in ("true", "1", "yes")
    else:
        show_debug = default_debug

    log_level = os.getenv("LOG_LEVEL", "INFO" if env == "production" else "DEBUG").upper()

    try:
        max_upload_mb = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    except ValueError:
        max_upload_mb = 10

    try:
        timeout_sec = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))
    except ValueError:
        timeout_sec = 45

    try:
        api_rate_limit = max(1, int(os.getenv("FOLIOSHIELD_API_RATE_LIMIT_PER_MIN", "120")))
    except ValueError:
        api_rate_limit = 120

    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except ValueError:
            return default

    cors_origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "FOLIOSHIELD_API_CORS_ORIGINS", "http://localhost:8501,http://localhost:3000").split(",")
        if origin.strip()
    )

    return Settings(
        environment=env,
        llama_provider=provider,
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        together_api_key=os.getenv("TOGETHER_API_KEY") or None,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        llama_text_model=os.getenv("LLAMA_TEXT_MODEL") or None,
        llama_vision_model=os.getenv("LLAMA_VISION_MODEL") or None,
        merchant_name=os.getenv("FOLIOSHIELD_MERCHANT_NAME", "Grand Horizon Resort & Suites"),
        hotel_contact_email=os.getenv("HOTEL_CONTACT_EMAIL", "disputes@grandhorizonresort.com"),
        max_upload_size_mb=max_upload_mb,
        allowed_extensions=("pdf", "csv", "png", "jpg", "jpeg"),
        enable_test_scenarios=enable_test_scenarios,
        show_debug_details=show_debug,
        request_timeout_seconds=timeout_sec,
        log_dir=os.getenv("LOG_DIR", "logs"),
        log_level=log_level,
        exhibit_store_dir=os.getenv("FOLIOSHIELD_EXHIBIT_DIR", "data/exhibits"),
        case_db_path=os.getenv("FOLIOSHIELD_CASE_DB", "data/cases.db"),
        api_key=os.getenv("FOLIOSHIELD_API_KEY") or None,
        api_allow_legacy_unauthenticated=(
            os.getenv("FOLIOSHIELD_API_ALLOW_LEGACY_UNAUTHENTICATED", "").strip().lower() in ("true", "1", "yes")
            if os.getenv("FOLIOSHIELD_API_ALLOW_LEGACY_UNAUTHENTICATED") is not None
            else env != "production"
        ),
        api_rate_limit_per_min=api_rate_limit,
        api_host=os.getenv("FOLIOSHIELD_API_HOST", "0.0.0.0"),
        api_port=_int_env("API_PORT", 8000),
        api_max_body_mb=max(1, _int_env("FOLIOSHIELD_API_MAX_BODY_MB", 15)),
        api_cors_origins=cors_origins,
        integration_root=os.getenv("FOLIOSHIELD_INTEGRATION_ROOT", "data/integrations"),
        webhook_resume_seconds=max(0, _int_env("FOLIOSHIELD_WEBHOOK_RESUME_SECONDS", 0)),
        webhook_secret_key=os.getenv("FOLIOSHIELD_WEBHOOK_SECRET_KEY") or None,
        audit_hmac_key=os.getenv("AUDIT_HMAC_KEY") or None,
        database_url=os.getenv("DATABASE_URL") or None,
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        s3_bucket_name=os.getenv("S3_BUCKET_NAME") or None,
    )


# Default singleton instance for standard imports
config = get_settings()
