"""
validator.py — Employment Intent Validation
Validates that results contain primary keyword + (secondary keyword OR hashtag).
"""
from __future__ import annotations

from typing import Any

from .config import HASHTAGS, PRIMARY_KEYWORDS, SECONDARY_KEYWORDS


def _normalize(text: str) -> str:
    return text.lower().strip()


def validate_employment_intent(
    text: str,
    primary_keywords: list[str] | None = None,
    secondary_keywords: list[str] | None = None,
    hashtags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Validate that text contains:
    1. At least one primary keyword
    2. At least one secondary keyword OR hashtag

    Returns dict with is_valid, matched_primary, matched_secondary, matched_hashtags.
    """
    pks = [_normalize(k) for k in (primary_keywords or PRIMARY_KEYWORDS)]
    sks = [_normalize(k) for k in (secondary_keywords or SECONDARY_KEYWORDS)]
    hts = [h.lower().lstrip("#") for h in (hashtags or HASHTAGS)]

    lower = _normalize(text)

    matched_primary = [k for k in pks if k in lower]
    matched_secondary = [k for k in sks if k in lower]
    matched_hashtags = [h for h in hts if f"#{h}" in lower or h in lower]

    has_primary = len(matched_primary) > 0
    has_context = len(matched_secondary) > 0 or len(matched_hashtags) > 0
    is_valid = has_primary and has_context

    return {
        "is_valid": is_valid,
        "has_primary": has_primary,
        "has_context": has_context,
        "matched_primary": matched_primary,
        "matched_secondary": matched_secondary,
        "matched_hashtags": matched_hashtags,
    }


def validate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validate a list of results. Each result must have 'text_ocr' or 'title' field.
    Returns only valid results with validation metadata attached.
    """
    validated = []
    for result in results:
        text = result.get("text_ocr") or result.get("title") or result.get("text") or ""
        if not text:
            result["validation"] = {
                "is_valid": False,
                "reason": "no_text_available",
            }
            continue

        v = validate_employment_intent(text)
        result["validation"] = v
        if v["is_valid"]:
            validated.append(result)

    return validated
