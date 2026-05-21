"""Import BibTeX and optional manual metadata into Paper records."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import shutil
from pathlib import Path
from typing import Any

import bibtexparser
import yaml
from bibtexparser.bparser import BibTexParser

from papergraph.models import Paper, utc_now_iso
from papergraph.utils import (
    clean_doi,
    clean_string,
    make_paper_id,
    normalize_key,
    parse_year,
    split_multi_value,
    split_reference_values,
    unique_clean_strings,
)


AUTHOR_SPLIT_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
REFERENCE_FIELDS = [
    "references",
    "reference",
    "cites",
    "citation",
    "citations",
    "bibliography",
]


def parse_bibtex_file(path: str | Path) -> list[Paper]:
    """Parse a BibTeX file into normalized Paper objects."""

    return parse_bibtex_text(Path(path).read_text(encoding="utf-8"))


def parse_zotero_sqlite(path: str | Path) -> list[Paper]:
    """Read paper metadata directly from a Zotero SQLite database, read-only."""

    db_path = Path(path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Zotero database not found: {db_path}")

    snapshot_path = _zotero_snapshot_path(db_path)
    _refresh_sqlite_snapshot(db_path, snapshot_path)

    uri = f"{snapshot_path.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
        connection.row_factory = sqlite3.Row
        item_rows = _zotero_items(connection)
        field_values = _zotero_field_values(connection)
        authors = _zotero_authors(connection)
        tags = _zotero_tags(connection)
        collections = _zotero_collections(connection)
        attachments = _zotero_attachments(connection, db_path.parent)

    papers: list[Paper] = []
    seen_ids: set[str] = set()
    for item in item_rows:
        item_id = int(item["itemID"])
        fields = field_values.get(item_id, {})
        title = clean_string(_first_present_mapping(fields, ["title", "caseName", "name"]))
        year = parse_year(_first_present_mapping(fields, ["date", "year"]))
        citekey = _citation_key_from_extra(fields.get("extra", "")) or clean_string(item["key"])
        paper_id = make_paper_id(citekey, title, year)
        if paper_id in seen_ids:
            paper_id = make_paper_id(f"{citekey}-{item_id}", title, year)
        seen_ids.add(paper_id)

        paper = Paper(
            id=paper_id,
            citekey=citekey,
            title=title,
            authors=authors.get(item_id, []),
            year=year,
            venue=clean_string(
                _first_present_mapping(
                    fields,
                    ["publicationTitle", "journalAbbreviation", "proceedingsTitle", "conferenceName", "publisher"],
                )
            ),
            doi=clean_doi(fields.get("DOI") or fields.get("doi")),
            abstract=clean_string(fields.get("abstractNote")),
            tags=tags.get(item_id, []),
            collections=collections.get(item_id, []),
            file_path=attachments.get(item_id),
            important_references=split_reference_values(
                _first_present_mapping(fields, ["references", "citation", "citations", "bibliography"])
            ),
            raw={
                "source": "zotero_sqlite",
                "source_path": str(db_path),
                "snapshot_path": str(snapshot_path),
                "itemID": item_id,
                "zotero_key": clean_string(item["key"]),
                "item_type": clean_string(item["typeName"]),
                "fields": fields,
            },
        )
        papers.append(paper)

    return papers


def _zotero_snapshot_path(db_path: Path) -> Path:
    stat = db_path.stat()
    key = hashlib.sha1(f"copy-v2-{db_path}-{stat.st_mtime_ns}-{stat.st_size}".encode("utf-8")).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / "graphature-zotero"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"zotero-{key}.sqlite"


def _refresh_sqlite_snapshot(source: Path, snapshot: Path) -> None:
    if snapshot.exists():
        return

    try:
        shutil.copy2(source, snapshot)
        for suffix in ["-wal", "-shm"]:
            source_sidecar = source.with_name(f"{source.name}{suffix}")
            snapshot_sidecar = snapshot.with_name(f"{snapshot.name}{suffix}")
            if snapshot_sidecar.exists():
                snapshot_sidecar.unlink()
            if source_sidecar.exists():
                shutil.copy2(source_sidecar, snapshot_sidecar)
    except OSError as exc:
        if snapshot.exists():
            snapshot.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not read Zotero's SQLite database. Close Zotero and try again, "
            "or use a Better BibTeX auto-export .bib file instead."
        ) from exc


def parse_bibtex_text(text: str) -> list[Paper]:
    """Parse BibTeX content into normalized Paper objects."""

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    database = bibtexparser.loads(text or "", parser=parser)

    papers: list[Paper] = []
    seen_ids: set[str] = set()
    for entry in database.entries:
        paper = _paper_from_bibtex_entry(entry)
        if paper.id in seen_ids:
            paper.id = make_paper_id(f"{paper.citekey}-{len(seen_ids)}", paper.title, paper.year)
        seen_ids.add(paper.id)
        papers.append(paper)
    return papers


def parse_manual_metadata_file(path: str | Path) -> dict[str, dict[str, Any]]:
    """Parse a YAML or JSON companion metadata file."""

    return parse_manual_metadata_text(Path(path).read_text(encoding="utf-8"))


def parse_manual_metadata_text(text: str) -> dict[str, dict[str, Any]]:
    """Parse companion metadata keyed by citekey.

    The preferred shape is:

    papers:
      citekey:
        topic: [...]
        manual_related: [...]
    """

    if not (text or "").strip():
        return {}

    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        payload = json.loads(text)

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Manual metadata must be a mapping or contain a 'papers' mapping.")

    papers = payload.get("papers", payload)
    if not isinstance(papers, dict):
        raise ValueError("Manual metadata 'papers' must be a mapping keyed by citekey.")

    return {normalize_key(citekey): data or {} for citekey, data in papers.items()}


def merge_manual_metadata(
    papers: list[Paper],
    manual_metadata: dict[str, dict[str, Any]] | None,
) -> list[Paper]:
    """Merge optional YAML/JSON metadata into imported papers by citekey."""

    if not manual_metadata:
        return papers

    for paper in papers:
        data = manual_metadata.get(normalize_key(paper.citekey))
        if not data:
            continue
        _merge_metadata_into_paper(paper, data)
    return papers


def _paper_from_bibtex_entry(entry: dict[str, Any]) -> Paper:
    citekey = clean_string(entry.get("ID") or entry.get("id") or entry.get("key"))
    title = clean_string(entry.get("title"))
    year = parse_year(entry.get("year") or entry.get("date"))
    authors = _split_authors(entry.get("author") or entry.get("editor"))
    venue = _first_present(entry, ["journal", "journaltitle", "booktitle", "conference", "publisher"])
    doi = clean_doi(entry.get("doi"))
    abstract = clean_string(entry.get("abstract"))
    tags = _tags_from_entry(entry)
    collections = _collections_from_entry(entry)
    file_path = clean_string(entry.get("file") or entry.get("local-url")) or None
    references = _references_from_entry(entry)

    return Paper(
        id=make_paper_id(citekey, title, year),
        citekey=citekey,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        abstract=abstract,
        tags=tags,
        collections=collections,
        file_path=file_path,
        important_references=references,
        raw=dict(entry),
    )


def _split_authors(value: Any) -> list[str]:
    text = clean_string(value)
    if not text:
        return []
    return unique_clean_strings(AUTHOR_SPLIT_RE.split(text))


def _first_present(entry: dict[str, Any], fields: list[str]) -> str:
    for field in fields:
        value = clean_string(entry.get(field))
        if value:
            return value
    return ""


def _first_present_mapping(mapping: dict[str, Any], fields: list[str]) -> str:
    for field in fields:
        value = clean_string(mapping.get(field))
        if value:
            return value
    return ""


def _citation_key_from_extra(extra: Any) -> str:
    text = clean_string(extra)
    for pattern in [
        r"(?im)^\s*citation\s+key\s*:\s*(.+?)\s*$",
        r"(?im)^\s*bibtex\s+key\s*:\s*(.+?)\s*$",
        r"(?im)^\s*@?citekey\s*:\s*(.+?)\s*$",
    ]:
        match = re.search(pattern, text)
        if match:
            return clean_string(match.group(1))
    return ""


def _zotero_items(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')
            ORDER BY i.itemID
            """
        )
    )


def _zotero_field_values(connection: sqlite3.Connection) -> dict[int, dict[str, str]]:
    values: dict[int, dict[str, str]] = {}
    for row in connection.execute(
        """
        SELECT itemData.itemID, fields.fieldName, itemDataValues.value
        FROM itemData
        JOIN fields ON fields.fieldID = itemData.fieldID
        JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
        """
    ):
        values.setdefault(int(row["itemID"]), {})[str(row["fieldName"])] = clean_string(row["value"])
    return values


def _zotero_authors(connection: sqlite3.Connection) -> dict[int, list[str]]:
    creator_columns = {row["name"] for row in connection.execute("PRAGMA table_info(creators)")}
    name_expr = "creators.name" if "name" in creator_columns else "''"
    rows = connection.execute(
        f"""
        SELECT itemCreators.itemID, creators.firstName, creators.lastName, creators.fieldMode,
               {name_expr} AS fullName, itemCreators.orderIndex
        FROM itemCreators
        JOIN creators ON creators.creatorID = itemCreators.creatorID
        ORDER BY itemCreators.itemID, itemCreators.orderIndex
        """
    )

    authors: dict[int, list[str]] = {}
    for row in rows:
        if int(row["fieldMode"] or 0) == 1:
            name = clean_string(row["fullName"] or row["lastName"])
        else:
            first = clean_string(row["firstName"])
            last = clean_string(row["lastName"])
            name = f"{last}, {first}".strip(", ") if first and last else last or first
        if name:
            authors.setdefault(int(row["itemID"]), []).append(name)
    return {item_id: unique_clean_strings(names) for item_id, names in authors.items()}


def _zotero_tags(connection: sqlite3.Connection) -> dict[int, list[str]]:
    tags: dict[int, list[str]] = {}
    for row in connection.execute(
        """
        SELECT itemTags.itemID, tags.name
        FROM itemTags
        JOIN tags ON tags.tagID = itemTags.tagID
        ORDER BY itemTags.itemID, tags.name
        """
    ):
        tags.setdefault(int(row["itemID"]), []).append(clean_string(row["name"]))
    return {item_id: unique_clean_strings(values) for item_id, values in tags.items()}


def _zotero_collections(connection: sqlite3.Connection) -> dict[int, list[str]]:
    collection_columns = {row["name"] for row in connection.execute("PRAGMA table_info(collections)")}
    parent_expr = "parentCollectionID" if "parentCollectionID" in collection_columns else "NULL"
    collection_names: dict[int, str] = {}
    collection_parents: dict[int, int | None] = {}
    for row in connection.execute(
        f"""
        SELECT collectionID, collectionName, {parent_expr} AS parentCollectionID
        FROM collections
        ORDER BY collectionID
        """
    ):
        collection_id = int(row["collectionID"])
        collection_names[collection_id] = clean_string(row["collectionName"])
        parent_id = row["parentCollectionID"]
        collection_parents[collection_id] = int(parent_id) if parent_id is not None else None

    path_cache: dict[int, str] = {}

    def collection_path(collection_id: int, seen: set[int] | None = None) -> str:
        if collection_id in path_cache:
            return path_cache[collection_id]
        seen = set(seen or set())
        if collection_id in seen:
            return collection_names.get(collection_id, "")
        seen.add(collection_id)

        name = collection_names.get(collection_id, "")
        parent_id = collection_parents.get(collection_id)
        parent_path = ""
        if parent_id is not None and parent_id in collection_names:
            parent_path = collection_path(parent_id, seen)
        path = " / ".join(part for part in [parent_path, name] if part)
        path_cache[collection_id] = path
        return path

    collections: dict[int, list[str]] = {}
    for row in connection.execute(
        """
        SELECT collectionItems.itemID, collectionItems.collectionID
        FROM collectionItems
        ORDER BY collectionItems.itemID, collectionItems.collectionID
        """
    ):
        path = collection_path(int(row["collectionID"]))
        if path:
            collections.setdefault(int(row["itemID"]), []).append(path)
    return {item_id: unique_clean_strings(values) for item_id, values in collections.items()}


def _zotero_attachments(connection: sqlite3.Connection, zotero_dir: Path) -> dict[int, str]:
    attachments: dict[int, str] = {}
    for row in connection.execute(
        """
        SELECT itemAttachments.parentItemID, itemAttachments.path, items.key
        FROM itemAttachments
        JOIN items ON items.itemID = itemAttachments.itemID
        WHERE itemAttachments.parentItemID IS NOT NULL
        ORDER BY itemAttachments.parentItemID
        """
    ):
        parent_id = int(row["parentItemID"])
        path = _resolve_zotero_attachment_path(clean_string(row["path"]), clean_string(row["key"]), zotero_dir)
        if path and parent_id not in attachments:
            attachments[parent_id] = path
    return attachments


def _resolve_zotero_attachment_path(path: str, attachment_key: str, zotero_dir: Path) -> str:
    if not path:
        return ""
    if path.lower().startswith("storage:"):
        filename = path.split(":", 1)[1].replace("\\", "/").split("/")[-1]
        return str(zotero_dir / "storage" / attachment_key / filename)
    return path


def _tags_from_entry(entry: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for field in ["keywords", "keyword", "tags", "zotero-tags"]:
        tags.extend(split_multi_value(entry.get(field)))
    return unique_clean_strings(tags)


def _collections_from_entry(entry: dict[str, Any]) -> list[str]:
    collections: list[str] = []
    for field in ["collection", "collections", "zotero-collection", "zotero-collections"]:
        collections.extend(split_multi_value(entry.get(field)))
    return unique_clean_strings(collections)


def _references_from_entry(entry: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for field in REFERENCE_FIELDS:
        references.extend(split_reference_values(entry.get(field)))
    return unique_clean_strings(references)


def _merge_metadata_into_paper(paper: Paper, data: dict[str, Any]) -> None:
    paper.title = clean_string(data.get("title")) or paper.title
    paper.venue = clean_string(data.get("venue")) or paper.venue
    paper.doi = clean_doi(data.get("doi")) or paper.doi
    paper.abstract = clean_string(data.get("abstract")) or paper.abstract
    paper.file_path = clean_string(data.get("file_path") or data.get("file")) or paper.file_path
    paper.notes_path = clean_string(data.get("notes_path")) or paper.notes_path
    paper.notes_content = clean_string(data.get("notes") or data.get("notes_content")) or paper.notes_content

    year = parse_year(data.get("year"))
    if year:
        paper.year = year

    if "read_status" in data:
        paper.read_status = bool(data["read_status"])

    authors = data.get("authors")
    if authors:
        paper.authors = unique_clean_strings(authors if isinstance(authors, list) else _split_authors(authors))

    paper.tags = unique_clean_strings([*paper.tags, *split_multi_value(data.get("tags"))])
    paper.collections = unique_clean_strings(
        [
            *paper.collections,
            *split_multi_value(data.get("collections")),
            *split_multi_value(data.get("collection")),
        ]
    )
    paper.topic_labels = unique_clean_strings(
        [
            *paper.topic_labels,
            *split_multi_value(data.get("topic")),
            *split_multi_value(data.get("topics")),
            *split_multi_value(data.get("topic_labels")),
        ]
    )
    paper.important_references = unique_clean_strings(
        [
            *paper.important_references,
            *split_reference_values(data.get("important_references")),
            *split_reference_values(data.get("references")),
            *split_reference_values(data.get("cites")),
            *split_reference_values(data.get("citations")),
            *split_reference_values(data.get("bibliography")),
            *split_reference_values(data.get("reference_text")),
        ]
    )
    paper.manual_related = unique_clean_strings(
        [
            *paper.manual_related,
            *split_multi_value(data.get("manual_related")),
            *split_multi_value(data.get("related")),
        ]
    )
    paper.raw["manual_metadata"] = data
    paper.modified_at = utc_now_iso()
