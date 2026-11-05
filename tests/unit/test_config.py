import pytest
from pydantic import ValidationError

from agentguard.config import SandboxOnlyError, load_settings

# _env_file=None: ignore any real .env on this machine, so tests never touch real keys.
KEYS = {"paypal_client_id": "test-id", "paypal_client_secret": "test-secret", "_env_file": None}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("PAYPAL_ENV", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def test_sandbox_is_accepted():
    s = load_settings(paypal_env="sandbox", **KEYS)
    assert s.paypal_base_url == "https://api-m.sandbox.paypal.com"


@pytest.mark.parametrize("env", ["live", "production", "SANDBOX", "", "sandbox "])
def test_anything_but_sandbox_is_refused(env):
    with pytest.raises(SandboxOnlyError):
        load_settings(paypal_env=env, **KEYS)


@pytest.mark.parametrize("url", [
    "https://api-m.paypal.com",                       # live host
    "http://api-m.sandbox.paypal.com",                # not https
    "https://api-m.sandbox.paypal.com.evil.example",  # lookalike host
])
def test_non_sandbox_base_url_is_refused(url):
    with pytest.raises(SandboxOnlyError):
        load_settings(paypal_env="sandbox", paypal_base_url=url, **KEYS)


def test_missing_keys_is_a_normal_validation_error():
    with pytest.raises(ValidationError):
        load_settings(paypal_env="sandbox", _env_file=None)


def test_secrets_never_print():
    s = load_settings(paypal_env="sandbox", **KEYS)
    assert "test-secret" not in repr(s) and "test-secret" not in str(s)
    assert "test-id" not in repr(s)


def test_env_var_live_is_refused(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(SandboxOnlyError):
        load_settings(**KEYS)
