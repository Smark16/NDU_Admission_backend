"""Zimbra Admin SOAP (JSON) client for account provisioning."""
from __future__ import annotations

import logging
from typing import Any

import requests

from .models import ZimbraIntegrationConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class ZimbraConfigError(Exception):
    pass


class ZimbraRequestError(Exception):
    def __init__(self, message: str, *, code: str | None = None, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _cfg() -> ZimbraIntegrationConfig:
    return ZimbraIntegrationConfig.get_solo()


def require_enabled_config() -> ZimbraIntegrationConfig:
    cfg = _cfg()
    if not cfg.is_enabled:
        raise ZimbraConfigError("Zimbra integration is disabled.")
    if not (cfg.admin_soap_url or "").strip():
        raise ZimbraConfigError("Zimbra Admin SOAP URL is not configured.")
    if not (cfg.admin_username or "").strip() or not (cfg.admin_password or "").strip():
        raise ZimbraConfigError("Zimbra admin username/password are not configured.")
    return cfg


def _soap_post(cfg: ZimbraIntegrationConfig, body: dict, *, auth_token: str | None = None) -> dict:
    url = (cfg.admin_soap_url or "").strip().rstrip("/")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    envelope: dict[str, Any] = {"Body": body}
    if auth_token:
        envelope["Header"] = {
            "context": {
                "_jsns": "urn:zimbra",
                "authToken": auth_token,
            }
        }
    try:
        response = requests.post(
            url,
            json=envelope,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            verify=bool(cfg.verify_ssl),
        )
    except requests.RequestException as exc:
        logger.exception("Zimbra SOAP request failed")
        raise ZimbraRequestError("Could not reach Zimbra Admin SOAP.", status_code=503) from exc

    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise ZimbraRequestError(
            f"Zimbra returned non-JSON (HTTP {response.status_code}).",
            status_code=502,
        ) from exc

    fault = None
    if isinstance(payload, dict):
        fault = (
            payload.get("Body", {}).get("Fault")
            or payload.get("Fault")
            or (payload.get("Body") or {}).get("Fault")
        )
    if fault:
        detail = fault.get("Reason", {}).get("Text") or fault.get("Detail") or str(fault)
        code = None
        try:
            code = fault.get("Detail", {}).get("Error", {}).get("Code")
        except Exception:
            code = None
        raise ZimbraRequestError(str(detail)[:500], code=code, status_code=502)

    if response.status_code >= 400:
        raise ZimbraRequestError(
            f"Zimbra HTTP {response.status_code}",
            status_code=response.status_code,
        )
    return payload if isinstance(payload, dict) else {}


def authenticate(cfg: ZimbraIntegrationConfig | None = None) -> str:
    cfg = cfg or require_enabled_config()
    payload = _soap_post(
        cfg,
        {
            "AuthRequest": {
                "_jsns": "urn:zimbraAdmin",
                "name": cfg.admin_username.strip(),
                "password": cfg.admin_password,
            }
        },
    )
    auth_resp = payload.get("Body", {}).get("AuthResponse", {}) or {}
    token = auth_resp.get("authToken")
    value = None
    if isinstance(token, list) and token:
        value = token[0].get("_content") if isinstance(token[0], dict) else token[0]
    elif isinstance(token, dict):
        value = token.get("_content")
    elif isinstance(token, str):
        value = token
    if not value:
        raise ZimbraRequestError("Zimbra auth succeeded but no authToken was returned.")
    return str(value)


def test_connection(cfg: ZimbraIntegrationConfig | None = None) -> dict:
    """Authenticate only; used by the Integrations UI test button."""
    cfg = cfg or _cfg()
    if not (cfg.admin_soap_url or "").strip():
        raise ZimbraConfigError("Zimbra Admin SOAP URL is not configured.")
    if not (cfg.admin_username or "").strip() or not (cfg.admin_password or "").strip():
        raise ZimbraConfigError("Zimbra admin username/password are not configured.")
    token = authenticate(cfg)
    return {"ok": True, "detail": "Authenticated with Zimbra Admin SOAP.", "token_prefix": token[:8]}


def get_account(email: str, *, auth_token: str, cfg: ZimbraIntegrationConfig | None = None) -> dict | None:
    cfg = cfg or require_enabled_config()
    try:
        payload = _soap_post(
            cfg,
            {
                "GetAccountRequest": {
                    "_jsns": "urn:zimbraAdmin",
                    "account": {"by": "name", "_content": email},
                }
            },
            auth_token=auth_token,
        )
    except ZimbraRequestError as exc:
        code = (exc.code or "").upper()
        msg = str(exc).lower()
        if "NO_SUCH_ACCOUNT" in code or "no such account" in msg:
            return None
        raise
    account = payload.get("Body", {}).get("GetAccountResponse", {}).get("account")
    if isinstance(account, list):
        return account[0] if account else None
    return account


def create_account(
    email: str,
    password: str,
    *,
    display_name: str,
    auth_token: str,
    cfg: ZimbraIntegrationConfig | None = None,
) -> dict:
    cfg = cfg or require_enabled_config()
    attrs = [
        {"n": "displayName", "_content": display_name or email},
        {"n": "zimbraPasswordMustChange", "_content": "TRUE"},
    ]
    payload = _soap_post(
        cfg,
        {
            "CreateAccountRequest": {
                "_jsns": "urn:zimbraAdmin",
                "name": email,
                "password": password,
                "a": attrs,
            }
        },
        auth_token=auth_token,
    )
    account = payload.get("Body", {}).get("CreateAccountResponse", {}).get("account")
    if isinstance(account, list):
        return account[0] if account else {}
    return account or {}


def set_account_status(
    email: str,
    status: str,
    *,
    auth_token: str,
    cfg: ZimbraIntegrationConfig | None = None,
) -> None:
    """Modify zimbraAccountStatus (e.g. 'closed' to deactivate, 'active' to
    reinstate) for an existing account. Deactivating locks the mailbox out
    without deleting any mail/data -- reversible by setting it back to
    'active'."""
    cfg = cfg or require_enabled_config()
    account = get_account(email, auth_token=auth_token, cfg=cfg)
    if not account:
        raise ZimbraRequestError(f"No such account: {email}", code="NO_SUCH_ACCOUNT")
    account_id = account.get("id")
    if not account_id:
        raise ZimbraRequestError(f"Could not resolve Zimbra account id for {email}")
    _soap_post(
        cfg,
        {
            "ModifyAccountRequest": {
                "_jsns": "urn:zimbraAdmin",
                "id": account_id,
                "a": [{"n": "zimbraAccountStatus", "_content": status}],
            }
        },
        auth_token=auth_token,
    )


def add_distribution_list_member(
    dl_email: str,
    member_email: str,
    *,
    auth_token: str,
    cfg: ZimbraIntegrationConfig | None = None,
) -> None:
    cfg = cfg or require_enabled_config()
    _soap_post(
        cfg,
        {
            "AddDistributionListMemberRequest": {
                "_jsns": "urn:zimbraAdmin",
                "dl": {"by": "name", "_content": dl_email},
                "dlm": [{"_content": member_email}],
            }
        },
        auth_token=auth_token,
    )
