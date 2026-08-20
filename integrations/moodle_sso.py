"""Signed Moodle LMS launch URLs (STEWARD → student browser → Moodle SSO)."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import quote, urlencode

DEFAULT_LAUNCH_TTL_SECONDS = 120
SSO_PATH = "/auth/ndu_erp/sso.php"


def moodle_launch_signing_secret(cfg) -> str:
    """
    Prefer dedicated launch secret; fall back to Django SECRET_KEY only for
    local/dev — production must set launch_signing_secret (same value Moodle uses).
    """
    secret = (getattr(cfg, "launch_signing_secret", None) or "").strip()
    if secret:
        return secret
    return ""


def build_launch_signature(*, reg_no: str, exp: int, secret: str) -> str:
    message = f"{reg_no}|{exp}".encode("utf-8")
    key = (secret or "").encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def build_moodle_sso_launch_url(
    *,
    base_url: str,
    reg_no: str,
    secret: str,
    ttl_seconds: int = DEFAULT_LAUNCH_TTL_SECONDS,
    now: int | None = None,
) -> dict:
    """
    Build https://moodle…/auth/ndu_erp/sso.php?reg_no=…&exp=…&sig=…

    Returns dict with launch_url, exp, reg_no, ttl_seconds.
    """
    root = (base_url or "").strip().rstrip("/")
    registration = (reg_no or "").strip()
    if not root:
        raise ValueError("Moodle base URL is not configured.")
    if not registration:
        raise ValueError("Registration number is required.")
    if not (secret or "").strip():
        raise ValueError(
            "Moodle launch signing secret is not configured. "
            "Rotate the Moodle API key (or set the SSO signing secret) so STEWARD and Moodle share the same secret."
        )

    ttl = max(60, min(int(ttl_seconds or DEFAULT_LAUNCH_TTL_SECONDS), 180))
    exp = int(now if now is not None else time.time()) + ttl
    sig = build_launch_signature(reg_no=registration, exp=exp, secret=secret)
    query = urlencode(
        {
            "reg_no": registration,
            "exp": str(exp),
            "sig": sig,
        },
        quote_via=quote,
    )
    # urljoin keeps host; SSO_PATH is absolute-from-root style
    launch_url = f"{root}{SSO_PATH}?{query}"
    return {
        "launch_url": launch_url,
        "reg_no": registration,
        "exp": exp,
        "ttl_seconds": ttl,
        "moodle_base_url": root,
    }


def verify_launch_signature(
    *,
    reg_no: str,
    exp: int | str,
    sig: str,
    secret: str,
    now: int | None = None,
) -> bool:
    """Optional helper for tests / local verify."""
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    clock = int(now if now is not None else time.time())
    if exp_i < clock:
        return False
    expected = build_launch_signature(reg_no=reg_no, exp=exp_i, secret=secret)
    return hmac.compare_digest(expected, (sig or "").strip())
