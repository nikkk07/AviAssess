"""
Application configuration (Pydantic Settings).

WHY this module exists:
    Secrets and environment-specific values must NEVER be hardcoded — they come
    from environment variables (set in the Render dashboard for this service).
    Pydantic Settings reads them once, validates types, and gives us a single
    typed `settings` object the rest of the app imports.

CRITICAL for auth:
    JWT_SECRET_KEY must be set to the EXACT same value as the separate auth
    service that ISSUES the tokens. This scoring service only VERIFIES tokens,
    so a matching secret + matching algorithm is what makes signatures line up.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, loaded from the environment (or a .env file)."""

    # ─────────────────────────────────────────────
    # JWT verification.
    # No default for the secret on purpose: a missing JWT_SECRET_KEY should be a
    # hard startup failure, not a silent fall-back to an insecure default.
    # ─────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    # ─────────────────────────────────────────────
    # Session tokens (stateless — the signed token IS the session state).
    # SESSION_SECRET is a SEPARATE secret from JWT_SECRET_KEY on purpose:
    #   * JWT_SECRET_KEY is shared with the auth service to verify LOGIN tokens.
    #   * SESSION_SECRET is owned solely by THIS service to sign SESSION tokens.
    # Reusing one secret for both would let a login token be replayed as a
    # session token (and vice-versa). Also no default → fail loud if unset.
    # ─────────────────────────────────────────────
    SESSION_SECRET: str
    SESSION_TTL_SECONDS: int = 1800

    # ─────────────────────────────────────────────
    # Data sources (local for dev; swappable for R2 in Phase 5).
    # ─────────────────────────────────────────────
    QUESTIONS_PATH: str = "tests/fixtures/sample_qa.json"
    CONFIG_PATH: str = "config.json"

    # ─────────────────────────────────────────────
    # CORS + admin gating. These arrive as comma-separated strings (env vars
    # are flat); the *_list / *_set properties parse them. We never allow "*".
    # ─────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    ADMIN_USER_IDS: str = ""  # comma-separated UUIDs allowed to write config

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def admin_user_ids_set(self) -> set[str]:
        return {u.strip() for u in self.ADMIN_USER_IDS.split(",") if u.strip()}

    @model_validator(mode="after")
    def _secrets_must_differ(self) -> "Settings":
        """Refuse to start if the two secrets are identical — a security mistake."""
        if self.SESSION_SECRET == self.JWT_SECRET_KEY:
            raise ValueError(
                "SESSION_SECRET must be different from JWT_SECRET_KEY "
                "(separate secrets for login vs session tokens)."
            )
        return self

    # Reads from a local .env in development; in production the values come from
    # real environment variables. extra="ignore" so unrelated env vars (R2, etc.)
    # added later don't break startup here.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Single shared instance imported across the app.
settings = Settings()
