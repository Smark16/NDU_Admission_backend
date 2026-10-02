"""Zimbra domain preauth -- single sign-on launch into webmail.

Zimbra's preauth servlet lets a trusted external system (STEWARD) hand a
student a one-time signed URL that logs them straight into webmail, without
re-entering their Zimbra password. The domain preauth key is generated on
the mail server with:

    zmprov gdpak <domain>

and must be pasted into ZimbraIntegrationConfig.preauth_key (Integrations
admin page) before this will work.

Algorithm (per Zimbra's documented preauth spec):
    preauth = HMAC-SHA1(key, "{account}|{by}|{expires}|{timestamp}")
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

DEFAULT_VALID_FOR_MS = 60_000  # preauth token validity window


def build_zimbra_preauth_url(*, base_url: str, account_email: str, preauth_key: str) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    account_email = (account_email or "").strip().lower()
    preauth_key = (preauth_key or "").strip()
    if not base_url:
        raise ValueError("Zimbra webmail base URL is not configured.")
    if not account_email:
        raise ValueError("No university email on record for this student.")
    if not preauth_key:
        raise ValueError("Zimbra preauth key is not configured. Contact ICT.")

    timestamp = int(time.time() * 1000)
    expires = 0  # 0 = use the server's default preauth token lifetime
    by = "name"

    data = f"{account_email}|{by}|{expires}|{timestamp}"
    preauth = hmac.new(
        preauth_key.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    params = {
        "account": account_email,
        "by": by,
        "timestamp": timestamp,
        "expires": expires,
        "preauth": preauth,
    }
    return f"{base_url}/service/preauth?{urlencode(params)}"
