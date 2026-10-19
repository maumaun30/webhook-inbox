"""Signature checks. Secret per source comes from env: SECRET_<SOURCE> (e.g. SECRET_SHOPIFY).

Returns "valid", "invalid", or "unchecked" (no secret set or no known signature header).
Payloads are always stored regardless of the result.
"""

import base64
import hashlib
import hmac
import os
import time


def _secret(source: str) -> str | None:
    return os.getenv("SECRET_" + source.upper().replace("-", "_"))


def _hmac(secret: str, msg: bytes) -> bytes:
    return hmac.new(secret.encode(), msg, hashlib.sha256).digest()


def _eq(a: str, b: str) -> str:
    return "valid" if hmac.compare_digest(a.strip(), b.strip()) else "invalid"


def verify(source: str, method: str, url: str, headers: dict, body: bytes) -> str:
    secret = _secret(source)
    if not secret:
        return "unchecked"
    h = {k.lower(): v for k, v in headers.items()}

    # Shopify: base64(HMAC-SHA256(raw body))
    if sig := h.get("x-shopify-hmac-sha256"):
        return _eq(base64.b64encode(_hmac(secret, body)).decode(), sig)

    # HubSpot v3: base64(HMAC-SHA256(method + uri + body + timestamp)), 5-min window
    if sig := h.get("x-hubspot-signature-v3"):
        ts = h.get("x-hubspot-request-timestamp", "")
        if not ts.isdigit() or abs(time.time() * 1000 - int(ts)) > 300_000:
            return "invalid"
        msg = (method + url).encode() + body + ts.encode()
        return _eq(base64.b64encode(_hmac(secret, msg)).decode(), sig)

    # Generic hex HMAC-SHA256 (GitHub-style "sha256=<hex>", or plain hex)
    for name in ("x-hub-signature-256", "x-signature"):
        if sig := h.get(name):
            return _eq(_hmac(secret, body).hex(), sig.removeprefix("sha256="))

    return "unchecked"
