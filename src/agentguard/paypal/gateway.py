"""PayPal gateway: the only code in AgentGuard that moves money.

Built on the APIMatic-generated `paypal-server-sdk`, following the PayPal Server SDK Context Plugin's Python
skills (client initialisation, OAuth, error handling, testing).

Rules this module enforces (each one has a test):
1. Sandbox only. The SDK environment is set explicitly AND the resolved base URL is checked, because
   `Environment.PRODUCTION == 0`, so a stray 0 would select live.
2. Payment STATUS decides, never the HTTP code. A declined card returns HTTP 201 with status DENIED.
3. Every money-moving call carries a PayPal-Request-Id chosen by the caller, so a retry reuses it and
   PayPal returns the same result instead of charging twice.
4. No automatic retries on POST. The SDK only retries GET/PUT; we keep max_retries=0 for money calls.
5. A void with no response body is confirmed by reading the authorisation back.
"""

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

import requests
from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
from paypalserversdk.api_helper import APIHelper
from paypalserversdk.configuration import Environment
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.capture_request import CaptureRequest
from paypalserversdk.models.card_request import CardRequest
from paypalserversdk.models.card_stored_credential import CardStoredCredential
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payment_initiator import PaymentInitiator
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.models.stored_payment_source_payment_type import StoredPaymentSourcePaymentType
from paypalserversdk.models.stored_payment_source_usage_type import StoredPaymentSourceUsageType
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from agentguard.config import SANDBOX_HOST, SandboxOnlyError, Settings

SUPPORTED_CURRENCIES = {"USD"}  # sandbox is US; money() assumes 2 decimal places (review B4)
AUTHORIZED = "CREATED"  # PayPal's authorisation status for "funds held, ready to capture"


class PayPalError(Exception):
    """A PayPal call failed. Carries what you need to report it (never secrets)."""

    def __init__(self, message: str, http_status: int | None = None, debug_id: str | None = None,
                 issue: str | None = None):
        super().__init__(message)
        self.http_status, self.debug_id, self.issue = http_status, debug_id, issue


@dataclass(frozen=True)
class AuthorizationResult:
    order_id: str | None
    authorization_id: str | None
    status: str | None          # authorisation status: CREATED, DENIED, PENDING...
    order_status: str | None
    expires_at: str | None
    vault_id: str | None
    http_status: int
    debug_id: str | None
    latency_ms: int

    @property
    def authorized(self) -> bool:
        """True only when PayPal says the funds are held. HTTP 201 alone means nothing."""
        return self.status == AUTHORIZED and self.authorization_id is not None


@dataclass(frozen=True)
class SettlementResult:
    action: str                 # "capture" or "void"
    authorization_id: str
    capture_id: str | None
    status: str | None          # capture: COMPLETED/PENDING/DECLINED...; void: VOIDED
    http_status: int
    debug_id: str | None
    latency_ms: int

    @property
    def succeeded(self) -> bool:
        return self.status == ("COMPLETED" if self.action == "capture" else "VOIDED")


# ---------------------------------------------------------------- payment sources
def vaulted_card(vault_id: str) -> PaymentSource:
    """A saved card charged by the merchant with no buyer present (the agent case, proven in the spike)."""
    return PaymentSource(card=CardRequest(
        vault_id=vault_id,
        stored_credential=CardStoredCredential(
            payment_initiator=PaymentInitiator.MERCHANT,
            payment_type=StoredPaymentSourcePaymentType.UNSCHEDULED,
            usage=StoredPaymentSourceUsageType.SUBSEQUENT)))


def money(amount: Decimal | str) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ValueError("amount must be positive")
    return f"{value:.2f}"


# ---------------------------------------------------------------- helpers
def _get(obj, *path):
    """Walk SDK models / lists safely; missing pieces give None."""
    for step in path:
        if obj is None:
            return None
        if isinstance(step, int):
            obj = obj[step] if isinstance(obj, list) and len(obj) > step else None
        else:
            obj = getattr(obj, step, None)
    return obj


def _debug_id(headers) -> str | None:
    if not headers:
        return None
    for key, value in dict(headers).items():
        if key.lower() == "paypal-debug-id":
            return value
    return None


def _status_str(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


class PayPalGateway:
    """Thin, tested wrapper around the PayPal Server SDK. Build once, reuse (the SDK caches the token)."""

    def __init__(self, settings: Settings, *, http_client_instance=None, timeout: int = 30):
        creds = ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.paypal_client_id.get_secret_value(),
            o_auth_client_secret=settings.paypal_client_secret.get_secret_value())
        kwargs = {"environment": Environment.SANDBOX, "client_credentials_auth_credentials": creds,
                  "timeout": timeout, "max_retries": 0}
        if http_client_instance is not None:
            kwargs["http_client_instance"] = http_client_instance
        self._client = PaypalServersdkClient(**kwargs)
        host = urlparse(self._client.config.get_base_uri()).hostname
        if host != SANDBOX_HOST:  # belt and braces: never trust the enum alone
            raise SandboxOnlyError(f"PayPal SDK resolved to {host}, not the sandbox")

    # -- calls ------------------------------------------------------------------------------------
    def _call(self, fn, options: dict, what: str):
        start = time.perf_counter()
        try:
            response = fn(options)
        except ApiException as err:
            issue = None
            details = _get(err, "details") or []
            if details:
                issue = f"{_get(details[0], 'issue')}: {_get(details[0], 'description')}"
            debug_id = getattr(err, "debug_id", None) or _debug_id(_get(err, "response", "headers"))
            raise PayPalError(f"PayPal {what} failed", getattr(err, "response_code", None), debug_id,
                              issue) from None
        except AuthValidationException:
            raise PayPalError(f"PayPal {what}: could not get an access token (check sandbox keys)") from None
        except requests.RequestException as err:  # network, proxy, timeout: outcome UNKNOWN
            raise PayPalError(f"PayPal {what}: network error ({type(err).__name__}); outcome unknown, "
                              "retry with the SAME request id") from None
        return response, round((time.perf_counter() - start) * 1000)

    def authorize(self, *, amount: Decimal | str, currency: str, payment_source: PaymentSource,
                  request_id: str, reference_id: str, description: str = "",
                  custom_id: str = "") -> AuthorizationResult:
        """Create an AUTHORIZE order (funds held, not taken). Never CAPTURE here: holding is the point."""
        if not request_id:
            raise ValueError("request_id is required for money-moving calls")
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"currency {currency!r} not supported (allowed: {sorted(SUPPORTED_CURRENCIES)})")
        body = OrderRequest(
            intent=CheckoutPaymentIntent.AUTHORIZE,
            purchase_units=[PurchaseUnitRequest(
                reference_id=reference_id, description=description[:127] or APIHelper.SKIP,
                custom_id=custom_id[:127] or APIHelper.SKIP,   # receipt / mandate fingerprint (decision D2)
                amount=AmountWithBreakdown(currency_code=currency, value=money(amount)))],
            payment_source=payment_source)
        resp, ms = self._call(self._client.orders.create_order,
                              {"body": body, "paypal_request_id": request_id, "prefer": "return=representation"},
                              "create order")
        order = resp.body
        auth = _get(order, "purchase_units", 0, "payments", "authorizations", 0)
        if auth is None and _status_str(_get(order, "status")) == "APPROVED":
            resp, more = self._call(self._client.orders.authorize_order,
                                    {"id": _get(order, "id"), "paypal_request_id": request_id + "-auth",
                                     "prefer": "return=representation"}, "authorize order")
            ms += more
            order = resp.body
            auth = _get(order, "purchase_units", 0, "payments", "authorizations", 0)
        return AuthorizationResult(
            order_id=_get(order, "id"), authorization_id=_get(auth, "id"),
            status=_status_str(_get(auth, "status")), order_status=_status_str(_get(order, "status")),
            expires_at=_get(auth, "expiration_time"),
            vault_id=_get(order, "payment_source", "card", "attributes", "vault", "id"),
            http_status=resp.status_code, debug_id=_debug_id(resp.headers), latency_ms=ms)

    def capture(self, authorization_id: str, *, request_id: str) -> SettlementResult:
        """Take the held money (buyer approved). Same request_id = same capture, never a second charge."""
        if not request_id:
            raise ValueError("request_id is required for money-moving calls")
        resp, ms = self._call(self._client.payments.capture_authorized_payment,
                              {"authorization_id": authorization_id, "paypal_request_id": request_id,
                               "prefer": "return=representation", "body": CaptureRequest(final_capture=True)},
                              "capture")
        return SettlementResult("capture", authorization_id, _get(resp.body, "id"),
                                _status_str(_get(resp.body, "status")), resp.status_code,
                                _debug_id(resp.headers), ms)

    def void(self, authorization_id: str, *, request_id: str) -> SettlementResult:
        """Release the held money (buyer rejected). Costs $0 in fees, unlike a refund."""
        if not request_id:
            raise ValueError("request_id is required for money-moving calls")
        resp, ms = self._call(self._client.payments.void_payment,
                              {"authorization_id": authorization_id, "paypal_request_id": request_id,
                               "prefer": "return=representation"}, "void")
        status = _status_str(_get(resp.body, "status"))
        if status is None:  # 204 No Content: confirm by reading the authorisation, don't assume
            status = self.authorization_status(authorization_id)
        return SettlementResult("void", authorization_id, None, status, resp.status_code,
                                _debug_id(resp.headers), ms)

    def authorization_status(self, authorization_id: str) -> str | None:
        resp, _ = self._call(self._client.payments.get_authorized_payment,
                             {"authorization_id": authorization_id}, "get authorization")
        return _status_str(_get(resp.body, "status"))
