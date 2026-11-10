"""Gateway tests against the fake PayPal, through the real SDK (no keys, no network)."""

import uuid

import pytest
import requests

from agentguard.config import SandboxOnlyError, load_settings
from agentguard.paypal import PayPalError, PayPalGateway, vaulted_card
from agentguard.paypal.fake import FakePayPal
from agentguard.paypal.gateway import money
from agentguard.paypal.testing import sandbox_test_card


@pytest.fixture
def fake():
    return FakePayPal()


@pytest.fixture
def gateway(fake):
    session = requests.Session()
    session.mount("https://", fake)
    settings = load_settings(paypal_env="sandbox", paypal_client_id="id", paypal_client_secret="secret",
                             _env_file=None)
    return PayPalGateway(settings, http_client_instance=session)


def rid():
    return str(uuid.uuid4())


def authorize(gateway, source=None, amount="24.99"):
    return gateway.authorize(amount=amount, currency="USD", payment_source=source or sandbox_test_card(),
                             request_id=rid(), reference_id="test")


def test_authorize_holds_funds(gateway, fake):
    result = authorize(gateway)
    assert result.authorized and result.status == "CREATED" and result.http_status == 201
    assert result.debug_id and result.expires_at
    order_call = next(c for c in fake.calls if c["path"] == "/v2/checkout/orders")
    assert order_call["body"]["intent"] == "AUTHORIZE"            # never CAPTURE at create
    assert order_call["body"]["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "24.99"}


def test_decline_is_201_but_not_authorized(gateway):
    """The finding from the spike: HTTP 201 does not mean the money is held."""
    result = authorize(gateway, sandbox_test_card(name="CCREJECT-REFUSED"))
    assert result.http_status == 201
    assert result.status == "DENIED"
    assert not result.authorized


def test_every_money_call_sends_a_request_id(gateway, fake):
    auth = authorize(gateway)
    gateway.capture(auth.authorization_id, request_id=rid())
    money_calls = [c for c in fake.calls if c["method"] == "POST" and c["path"] != "/v1/oauth2/token"]
    assert len(money_calls) == 2
    assert all(c["headers"].get("paypal-request-id") for c in money_calls)


@pytest.mark.parametrize("call", ["authorize", "capture", "void"])
def test_missing_request_id_is_refused_before_calling_paypal(gateway, fake, call):
    with pytest.raises(ValueError):
        if call == "authorize":
            gateway.authorize(amount="1", currency="USD", payment_source=sandbox_test_card(), request_id="",
                              reference_id="x")
        elif call == "capture":
            gateway.capture("AUTH1", request_id="")
        else:
            gateway.void("AUTH1", request_id="")
    assert not [c for c in fake.calls if c["path"] != "/v1/oauth2/token"]


def test_capture_replay_returns_same_capture_no_double_charge(gateway, fake):
    auth = authorize(gateway)
    key = rid()
    first = gateway.capture(auth.authorization_id, request_id=key)
    replay = gateway.capture(auth.authorization_id, request_id=key)
    assert first.succeeded and replay.succeeded
    assert first.capture_id == replay.capture_id
    assert (first.http_status, replay.http_status) == (201, 200)   # as measured in the live sandbox
    assert len(fake.captures) == 1


def test_second_capture_with_new_key_is_refused(gateway):
    auth = authorize(gateway)
    gateway.capture(auth.authorization_id, request_id=rid())
    with pytest.raises(PayPalError) as err:
        gateway.capture(auth.authorization_id, request_id=rid())
    assert err.value.http_status == 422
    assert "AUTHORIZATION_ALREADY_CAPTURED" in err.value.issue


def test_void_releases_the_hold(gateway):
    auth = authorize(gateway)
    result = gateway.void(auth.authorization_id, request_id=rid())
    assert result.succeeded and result.status == "VOIDED"


def test_void_without_body_is_confirmed_by_reading_back():
    fake = FakePayPal(void_returns_no_body=True)
    session = requests.Session()
    session.mount("https://", fake)
    gw = PayPalGateway(load_settings(paypal_env="sandbox", paypal_client_id="i", paypal_client_secret="s",
                                     _env_file=None), http_client_instance=session)
    auth = authorize(gw)
    result = gw.void(auth.authorization_id, request_id=rid())
    assert result.http_status == 204 and result.status == "VOIDED"
    assert fake.calls[-1]["method"] == "GET"     # it checked, it didn't assume


def test_cannot_void_after_capture(gateway):
    auth = authorize(gateway)
    gateway.capture(auth.authorization_id, request_id=rid())
    with pytest.raises(PayPalError) as err:
        gateway.void(auth.authorization_id, request_id=rid())
    assert err.value.http_status == 422


def test_vault_then_charge_with_no_buyer_present(gateway):
    saved = authorize(gateway, sandbox_test_card(save=True), amount="1.00")
    assert saved.vault_id
    agent_charge = authorize(gateway, vaulted_card(saved.vault_id), amount="12.50")
    assert agent_charge.authorized


def test_errors_carry_debug_id_not_secrets(gateway):
    with pytest.raises(PayPalError) as err:
        gateway.capture("NOPE", request_id=rid())
    assert err.value.http_status == 404 and err.value.debug_id
    assert "secret" not in str(err.value).lower()
    assert err.value.typed is True   # the SDK raised its typed ErrorException (APIMatic review G1)


def test_untyped_sdk_error_is_still_caught_and_flagged(gateway):
    from types import SimpleNamespace

    from paypalserversdk.exceptions.api_exception import ApiException

    def boom(_):
        raise ApiException("odd", SimpleNamespace(status_code=500, headers={"PayPal-Debug-Id": "dbg1"}))
    with pytest.raises(PayPalError) as err:
        gateway._call(boom, {}, "capture")
    assert err.value.typed is False and err.value.http_status == 500 and err.value.debug_id == "dbg1"
    assert "untyped" in str(err.value)


def test_token_failure_says_payment_not_sent_and_names_both_causes(gateway):
    from apimatic_core.exceptions.auth_validation_exception import AuthValidationException

    def no_token(_):
        raise AuthValidationException("token")
    with pytest.raises(PayPalError) as err:
        gateway._call(no_token, {}, "authorize")
    msg = str(err.value)
    assert "NOT sent" in msg and "keys wrong" in msg and "token service unavailable" in msg


@pytest.mark.parametrize("value,expected", [("24.99", "24.99"), ("10", "10.00"), ("0.005", "0.01")])
def test_money_formatting(value, expected):
    assert money(value) == expected


@pytest.mark.parametrize("value", ["0", "-1"])
def test_money_must_be_positive(value):
    with pytest.raises(ValueError):
        money(value)


def test_gateway_refuses_non_sandbox_sdk(monkeypatch):
    from paypalserversdk.configuration import Configuration
    monkeypatch.setattr(Configuration, "get_base_uri", lambda self, server=None: "https://api-m.paypal.com")
    with pytest.raises(SandboxOnlyError):
        PayPalGateway(load_settings(paypal_env="sandbox", paypal_client_id="i", paypal_client_secret="s",
                                    _env_file=None))


def test_network_failure_becomes_paypal_error():
    class Down(FakePayPal):
        def send(self, request, **kwargs):
            raise requests.ConnectionError("proxy said no")
    session = requests.Session()
    session.mount("https://", Down())
    gw = PayPalGateway(load_settings(paypal_env="sandbox", paypal_client_id="i", paypal_client_secret="s",
                                     _env_file=None), http_client_instance=session)
    with pytest.raises(PayPalError) as err:
        gw.capture("AUTH1", request_id=rid())
    assert "outcome unknown" in str(err.value) or "access token" in str(err.value)


def test_only_usd_is_accepted(gateway, fake):
    with pytest.raises(ValueError):
        gateway.authorize(amount="1000", currency="JPY", payment_source=sandbox_test_card(), request_id=rid(),
                          reference_id="x")
    assert not [c for c in fake.calls if c["path"] != "/v1/oauth2/token"]


def test_product_code_never_imports_the_test_card_helper():
    """Review B2: card numbers stay out of product code."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "src" / "agentguard"
    offenders = [p.name for p in src.rglob("*.py") if p.name != "testing.py"
                 and ("sandbox_test_card" in p.read_text(encoding="utf-8") or "4012888888881881" in
                      p.read_text(encoding="utf-8"))]
    assert offenders == []
