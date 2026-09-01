"""Server-to-server calls from ERP to the e-voting API."""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20


class EvotingConfigError(Exception):
    pass


class EvotingRequestError(Exception):
    def __init__(self, message: str, status_code: int = 502, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _config() -> tuple[str, str]:
    base = (getattr(settings, "EVOTING_BASE_URL", None) or "").strip().rstrip("/")
    key = (getattr(settings, "EVOTING_API_KEY", None) or "").strip()
    if not base or not key:
        raise EvotingConfigError(
            "E-voting integration is not configured. Set EVOTING_BASE_URL and EVOTING_API_KEY."
        )
    return base, key


def evoting_request(method: str, path: str, *, reg_no: str | None = None, json=None, timeout: int = DEFAULT_TIMEOUT):
    base, key = _config()
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    headers = {
        "X-API-Key": key,
        "Accept": "application/json",
    }
    if reg_no:
        headers["X-Student-Number"] = reg_no
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.exception("E-voting request failed: %s %s", method, url)
        raise EvotingRequestError("Could not reach the voting service.", status_code=503) from exc

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"detail": response.text[:300]}

    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise EvotingRequestError(
            detail or "Voting service returned an error.",
            status_code=response.status_code,
            payload=payload,
        )
    return payload
