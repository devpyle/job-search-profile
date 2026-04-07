"""Shared normalization helpers used across source parsers."""

import html
import re


def _clean_desc(text: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def format_salary_text(sal_min, sal_max) -> str:
    """Format structured salary fields into a display string like '$125,000–$175,000'.
    Returns empty string if sal_min is falsy."""
    if not sal_min:
        return ""
    try:
        text = f"${int(sal_min):,}–${int(sal_max):,}" if sal_max else f"${int(sal_min):,}+"
    except (ValueError, TypeError):
        return ""
    return text


def matches_keywords(title: str, keywords: list[str]) -> bool:
    """Return True if title contains any keyword (case-insensitive)."""
    t = title.lower()
    return any(w in t for w in keywords)
