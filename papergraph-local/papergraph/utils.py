"""Small normalization helpers used across Graphature."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any


MULTI_VALUE_SPLIT_RE = re.compile(r"\s*(?:;|\||\n|,)\s*")
REFERENCE_SPLIT_RE = re.compile(r"\s*(?:\n+|\|+|;)\s*")
COMMA_REFERENCE_TOKEN_RE = re.compile(r"^[\w@:/.\-]+$")
WHITESPACE_RE = re.compile(r"\s+")
NON_KEY_RE = re.compile(r"[^a-z0-9]+")


def clean_string(value: Any) -> str:
    """Normalize common BibTeX/YAML scalar values into a readable string."""

    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = text.strip().strip("{}")
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def normalize_key(value: Any) -> str:
    """Return a lowercase key for case-insensitive matching."""

    return clean_string(value).lower()


def compact_key(value: Any) -> str:
    """Return an alphanumeric-only key for title/reference matching."""

    return NON_KEY_RE.sub("", normalize_key(value))


def make_paper_id(citekey: str, title: str = "", year: int | None = None) -> str:
    """Create a stable internal paper id from the best available metadata."""

    source = citekey or f"{title}-{year or ''}"
    source = source or "untitled"
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    return f"paper-{digest}"


def ensure_list(value: Any) -> list[Any]:
    """Coerce a scalar or iterable value into a list."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def unique_clean_strings(values: Iterable[Any]) -> list[str]:
    """Return cleaned strings while preserving first-seen order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_string(value)
        if not text:
            continue
        key = text.lower()
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result


def split_multi_value(value: Any) -> list[str]:
    """Split BibTeX/YAML tag-like fields into a clean list."""

    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return unique_clean_strings(value)
    text = clean_string(value)
    if not text:
        return []
    return unique_clean_strings(part for part in MULTI_VALUE_SPLIT_RE.split(text) if part)


def split_reference_values(value: Any) -> list[str]:
    """Split reference-like fields while preserving full citation strings.

    Bibliographic references often contain commas inside author lists and titles,
    so this intentionally avoids comma-splitting unless the value looks like a
    compact citekey/DOI list.
    """

    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return unique_clean_strings(value)

    raw_text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip().strip("{}")
    if not raw_text:
        return []

    parts = [part for part in REFERENCE_SPLIT_RE.split(raw_text) if part.strip()]
    if len(parts) == 1 and "," in raw_text:
        comma_parts = [part.strip() for part in raw_text.split(",") if part.strip()]
        if len(comma_parts) > 1 and all(COMMA_REFERENCE_TOKEN_RE.match(part) for part in comma_parts):
            parts = comma_parts

    return unique_clean_strings(parts)


def parse_year(value: Any) -> int | None:
    """Extract a four-digit year if one is present."""

    text = clean_string(value)
    match = re.search(r"(18|19|20|21)\d{2}", text)
    return int(match.group(0)) if match else None


def clean_doi(value: Any) -> str:
    """Normalize DOI values, including DOI URLs."""

    text = clean_string(value)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()
