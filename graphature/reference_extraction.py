"""Local reference text extraction from attached PDFs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from graphature.models import Paper
from graphature.storage import DATA_DIR, ensure_project_dirs
from graphature.utils import clean_string, unique_clean_strings


REFERENCE_CACHE_FILE = DATA_DIR / "reference_cache.json"
PDF_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^{};|]+?\.pdf|/[^\s{};|]+?\.pdf)", re.IGNORECASE)
REFERENCE_HEADING_RE = re.compile(
    r"(?im)^\s*(references|bibliography|works\s+cited|literature\s+cited)\s*$"
)


def enrich_references_from_local_pdfs(papers: list[Paper]) -> tuple[list[Paper], dict[str, Any]]:
    """Append locally extracted PDF reference sections to paper reference lists."""

    try:
        from pypdf import PdfReader
    except ImportError:
        return papers, {
            "enabled": False,
            "reason": "Install pypdf to scan local PDF reference sections.",
            "papers_with_pdf": sum(1 for paper in papers if _pdf_paths_from_paper(paper)),
            "scanned": 0,
            "with_reference_text": 0,
        }

    cache = _load_cache()
    scanned = 0
    with_reference_text = 0
    papers_with_pdf = 0

    for paper in papers:
        paths = _pdf_paths_from_paper(paper)
        if not paths:
            continue
        papers_with_pdf += 1

        for path in paths:
            if not path.exists():
                continue
            scanned += 1
            reference_text = _cached_reference_text(path, cache, PdfReader)
            if not reference_text:
                continue
            with_reference_text += 1
            paper.important_references = unique_clean_strings([*paper.important_references, reference_text])
            break

    _save_cache(cache)
    return papers, {
        "enabled": True,
        "papers_with_pdf": papers_with_pdf,
        "scanned": scanned,
        "with_reference_text": with_reference_text,
    }


def _pdf_paths_from_paper(paper: Paper) -> list[Path]:
    raw_values = [paper.file_path or ""]
    raw_file = paper.raw.get("file") if isinstance(paper.raw, dict) else ""
    if raw_file and raw_file not in raw_values:
        raw_values.append(str(raw_file))

    paths: list[Path] = []
    for value in raw_values:
        text = _normalize_pdf_path_text(clean_string(value))
        if not text:
            continue
        for match in PDF_PATH_RE.findall(text):
            paths.append(Path(match).expanduser())
        if text.lower().endswith(".pdf") and not PDF_PATH_RE.search(text):
            paths.append(Path(text).expanduser())

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique_paths.append(path)
    return unique_paths


def _normalize_pdf_path_text(value: str) -> str:
    """Undo common BibTeX escaping in Zotero/Better BibTeX file fields."""

    text = value.replace("\\:", ":")
    while "\\\\" in text:
        text = text.replace("\\\\", "\\")
    return text


def _cached_reference_text(path: Path, cache: dict[str, Any], pdf_reader) -> str:
    try:
        stat = path.stat()
    except OSError:
        return ""

    key = str(path.resolve())
    signature = {"mtime": stat.st_mtime, "size": stat.st_size}
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return clean_string(cached.get("reference_text"))

    reference_text = _extract_reference_text(path, pdf_reader)
    cache[key] = {"signature": signature, "reference_text": reference_text}
    return reference_text


def _extract_reference_text(path: Path, pdf_reader) -> str:
    try:
        reader = pdf_reader(str(path))
        page_text = []
        for page in reader.pages:
            page_text.append(page.extract_text() or "")
    except Exception:
        return ""

    text = "\n".join(page_text)
    if not text.strip():
        return ""

    match = None
    for match in REFERENCE_HEADING_RE.finditer(text):
        pass

    if match:
        return clean_string(text[match.end() :])

    return clean_string(text[-40000:])


def _load_cache() -> dict[str, Any]:
    if not REFERENCE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(REFERENCE_CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    ensure_project_dirs()
    REFERENCE_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
