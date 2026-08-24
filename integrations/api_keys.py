"""API key generate / hash helpers for Moodle integration."""
from __future__ import annotations

import hashlib
import hmac
import secrets

def generate_moodle_api_key() -> str:
    return f"ndu_moodle_{secrets.token_urlsafe(32)}"

def hash_api_key(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()

def api_key_prefix(raw: str, *, length: int = 12) -> str:
    return (raw or "")[:length]

def api_keys_match(raw: str, stored_hash: str) -> bool:
    if not raw or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_key(raw), stored_hash)

