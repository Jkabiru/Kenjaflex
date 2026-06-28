"""
Safaricom Daraja API integration.

In MPESA_MOCK_MODE (default for local dev / tests), STK Push and B2C payout
calls are simulated as instantly successful so the rest of the payment flow
(unlocking search results, crediting field-agent payouts) can be built and
tested without sandbox Daraja credentials. Set MPESA_MOCK_MODE=False and
fill in DARAJA_* settings to go live -- only the two functions below need
real implementations; callers (routers) are unaffected.
"""
import base64
import logging
import uuid

import httpx

from app.config import get_settings
from app.utils import utcnow

logger = logging.getLogger("kejaflix.mpesa")
settings = get_settings()

DARAJA_BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}


def _get_access_token() -> str:
    base_url = DARAJA_BASE_URLS[settings.DARAJA_ENV]
    resp = httpx.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        auth=(settings.DARAJA_CONSUMER_KEY, settings.DARAJA_CONSUMER_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def initiate_stk_push(phone: str, amount: int, account_reference: str, description: str) -> dict:
    """Initiates Mpesa STK Push (C2B). Returns dict with at least
    `checkout_request_id` and `status` ('initiated' or 'failed')."""
    if settings.MPESA_MOCK_MODE:
        checkout_id = f"MOCK-{uuid.uuid4().hex[:12].upper()}"
        logger.info(
            "[MPESA MOCK] STK push phone=%s amount=%s ref=%s -> %s",
            phone, amount, account_reference, checkout_id,
        )
        return {"checkout_request_id": checkout_id, "status": "initiated", "mock": True}

    base_url = DARAJA_BASE_URLS[settings.DARAJA_ENV]
    token = _get_access_token()
    timestamp = utcnow().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{settings.DARAJA_SHORTCODE}{settings.DARAJA_PASSKEY}{timestamp}".encode()
    ).decode()

    payload = {
        "BusinessShortCode": settings.DARAJA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": settings.DARAJA_SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": f"{settings.DARAJA_CALLBACK_BASE_URL}/payments/mpesa/callback",
        "AccountReference": account_reference,
        "TransactionDesc": description,
    }
    resp = httpx.post(
        f"{base_url}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = resp.json()
    if data.get("ResponseCode") == "0":
        return {"checkout_request_id": data["CheckoutRequestID"], "status": "initiated", "mock": False}
    return {"checkout_request_id": None, "status": "failed", "raw": data, "mock": False}


def initiate_b2c_payout(phone: str, amount: int, remarks: str) -> dict:
    """Initiates Mpesa B2C payout (field agent reward withdrawal)."""
    if settings.MPESA_MOCK_MODE:
        receipt = f"MOCKB2C-{uuid.uuid4().hex[:10].upper()}"
        logger.info("[MPESA MOCK] B2C payout phone=%s amount=%s -> %s", phone, amount, receipt)
        return {"mpesa_receipt": receipt, "status": "success", "mock": True}

    # Production implementation: POST to /mpesa/b2c/v1/paymentrequest with
    # InitiatorName / SecurityCredential per Daraja B2C docs, then mark the
    # payout 'initiated' here and finalize status via the result callback.
    raise NotImplementedError("Wire up live Daraja B2C call here in production")
