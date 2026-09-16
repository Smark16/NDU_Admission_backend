"""Shared search helpers for finance / tuition ledger name lookups."""
from __future__ import annotations

import re

from django.db.models import Q

_TOKEN_SPLIT = re.compile(r"\s+")


def search_tokens(term: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split((term or "").strip()) if t]


def multi_token_name_q(term: str, *name_fields: str) -> Q:
    """
    Match multi-word names against separate first/middle/last fields.

    "John Doe" requires each token to appear in at least one name field
    (so first_name=John + last_name=Doe matches).
    """
    tokens = search_tokens(term)
    if not tokens or not name_fields:
        return Q()

    combined = Q()
    for token in tokens:
        token_q = Q()
        for field in name_fields:
            token_q |= Q(**{f"{field}__icontains": token})
        combined &= token_q
    return combined


def identity_or_name_search_q(
    term: str,
    *,
    identity_fields: tuple[str, ...] = (),
    name_fields: tuple[str, ...] = (),
) -> Q:
    """Full-term identity match OR multi-token name match."""
    term = (term or "").strip()
    if not term:
        return Q()

    identity_q = Q()
    for field in identity_fields:
        identity_q |= Q(**{f"{field}__icontains": term})

    name_q = multi_token_name_q(term, *name_fields)
    if identity_fields and name_fields:
        return identity_q | name_q
    if identity_fields:
        return identity_q
    return name_q
