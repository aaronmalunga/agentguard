"""Gateway tests against the fake PayPal, through the real SDK (no keys, no network)."""

import uuid

import pytest
import requests

from agentguard.config import SandboxOnlyError, load_settings
from agentguard.paypal import PayPalError, PayPalGateway, sandbox_test_card, vaulted_card
from agentguard.paypal.fake import FakePayPal
from agentguard.paypal.gateway import money


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
