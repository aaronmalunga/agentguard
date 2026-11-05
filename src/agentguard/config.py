"""Settings for AgentGuard.

Safety rule (INSTRUCTIONS.md section 5): the app refuses to start unless PAYPAL_ENV=sandbox
and the PayPal base URL is the sandbox host. Secrets are SecretStr, so they never print.
"""

from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SANDBOX_HOST = "api-m.sandbox.paypal.com"
REPO_ROOT = Path(__file__).resolve().parents[2]

# .env in the repo, or one folder above it (where the spike scripts keep it). Later files win.
ENV_FILES = (REPO_ROOT.parent / ".env", REPO_ROOT / ".env")


class SandboxOnlyError(RuntimeError):
    """Raised when the configuration points anywhere other than the PayPal sandbox."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    paypal_env: str
    paypal_client_id: SecretStr
    paypal_client_secret: SecretStr
    paypal_base_url: str = f"https://{SANDBOX_HOST}"

    @field_validator("paypal_env")
    @classmethod
    def must_be_sandbox(cls, value: str) -> str:
        if value != "sandbox":
            raise ValueError(f"PAYPAL_ENV must be 'sandbox', got {value!r}")
        return value

    @field_validator("paypal_base_url")
    @classmethod
    def must_be_sandbox_host(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname != SANDBOX_HOST:
            raise ValueError(f"PayPal base URL must be https://{SANDBOX_HOST}")
        return value


def load_settings(**overrides) -> Settings:
    """Load settings, turning any sandbox violation into one clear error."""
    try:
        return Settings(**overrides)
    except ValidationError as err:
        if any(e["loc"] and e["loc"][0] in ("paypal_env", "paypal_base_url") for e in err.errors()):
            raise SandboxOnlyError(
                "AgentGuard runs against the PayPal sandbox only. "
                "Set PAYPAL_ENV=sandbox and leave PAYPAL_BASE_URL unset."
            ) from None
        raise
