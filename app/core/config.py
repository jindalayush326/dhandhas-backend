from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dhandha Accounting API"
    env: str = "production"

    database_url: str = "sqlite:///./dhandas.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Auth
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    invitation_expire_days: int = 7
    frontend_base_url: str = "http://localhost:3000"
    max_members_per_company: int = 10

    # Login protection
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 60
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    refresh_token_cleanup_days: int = 7

    # OTP (email verification / login 2FA)
    otp_length: int = 6
    otp_expire_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    require_email_verification: bool = True

    # Email delivery. Empty smtp_host => emails are logged, not sent
    # (safe local-dev default; set real SMTP creds for production).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@dhandas.app"
    smtp_use_tls: bool = True

    # DB safety
    db_statement_timeout_ms: int = 15000

    # GST / HSN providers (swap via env only — see providers/factory.py)
    gst_provider: str = "gstinapi"
    gstinapi_api_key: str = ""
    request_timeout: int = 10

    cors_origins: str = "*"

    # Scan/OCR bounds — keep this endpoint bounded and predictable under load
    scan_max_upload_mb: int = 15
    scan_max_pdf_pages: int = 15

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
