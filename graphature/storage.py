"""Local cache and export helpers."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import networkx as nx

from graphature.models import Paper
from graphature.utils import ensure_list, normalize_key, unique_clean_strings


PROJECT_DIR = Path(__file__).resolve().parents[1] / "graphature_project"
DATA_DIR = PROJECT_DIR / "data"
EXPORTS_DIR = PROJECT_DIR / "exports"
NOTES_DIR = PROJECT_DIR / "notes"
OVERRIDES_FILE = DATA_DIR / "paper_overrides.json"
SOURCE_CONFIG_FILE = DATA_DIR / "source_config.json"


def ensure_project_dirs() -> None:
    """Create local project folders if they do not exist."""

    for directory in [DATA_DIR, EXPORTS_DIR, NOTES_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def save_uploaded_text(filename: str, text: str) -> Path:
    """Persist an uploaded text file into the local project data folder."""

    ensure_project_dirs()
    path = DATA_DIR / filename
    path.write_text(text, encoding="utf-8")
    return path


def save_papers_cache(papers: list[Paper], path: str | Path | None = None) -> Path:
    """Save normalized papers as JSON."""

    ensure_project_dirs()
    output_path = Path(path) if path else DATA_DIR / "papers_cache.json"
    output_path.write_text(json.dumps([paper.to_dict() for paper in papers], indent=2), encoding="utf-8")
    return output_path


def load_papers_cache(path: str | Path | None = None) -> list[Paper]:
    """Load normalized papers from JSON cache."""

    input_path = Path(path) if path else DATA_DIR / "papers_cache.json"
    if not input_path.exists():
        return []
    data = json.loads(input_path.read_text(encoding="utf-8"))
    return [Paper.from_dict(item) for item in data]


def load_paper_overrides(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load locally edited paper properties keyed by normalized citekey."""

    input_path = Path(path) if path else OVERRIDES_FILE
    if not input_path.exists():
        return {}
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {normalize_key(key): value for key, value in data.items() if isinstance(value, dict)}


def load_source_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load remembered local import paths."""

    input_path = Path(path) if path else SOURCE_CONFIG_FILE
    if not input_path.exists():
        return {}
    data = json.loads(input_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_source_config(config: dict[str, Any], path: str | Path | None = None) -> Path:
    """Persist remembered local import paths."""

    ensure_project_dirs()
    output_path = Path(path) if path else SOURCE_CONFIG_FILE
    output_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return output_path


def save_paper_overrides(overrides: dict[str, dict[str, Any]], path: str | Path | None = None) -> Path:
    """Persist locally edited paper properties."""

    ensure_project_dirs()
    output_path = Path(path) if path else OVERRIDES_FILE
    output_path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    return output_path


def apply_paper_overrides(papers: list[Paper], overrides: dict[str, dict[str, Any]]) -> list[Paper]:
    """Apply local property overrides to imported papers by citekey."""

    for paper in papers:
        data = overrides.get(normalize_key(paper.citekey))
        if not data:
            continue
        if "tags" in data:
            paper.tags = unique_clean_strings(ensure_list(data["tags"]))
        if "collections" in data:
            paper.collections = unique_clean_strings(ensure_list(data["collections"]))
        if "topic_labels" in data:
            paper.topic_labels = unique_clean_strings(ensure_list(data["topic_labels"]))
        if "read_status" in data:
            paper.read_status = bool(data["read_status"])
    return papers


def update_paper_overrides(
    papers: list[Paper],
    updates: dict[str, Any],
    path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Save override fields for the supplied papers and return all overrides."""

    overrides = load_paper_overrides(path)
    for paper in papers:
        key = normalize_key(paper.citekey)
        if not key:
            continue
        current = overrides.setdefault(key, {})
        for field, value in updates.items():
            if field in {"tags", "collections", "topic_labels"}:
                current[field] = unique_clean_strings(ensure_list(value))
            elif field == "read_status" and value is not None:
                current[field] = bool(value)
            elif value is not None:
                current[field] = value
    save_paper_overrides(overrides, path)
    return overrides


def graph_to_json(graph: nx.Graph) -> str:
    """Serialize a NetworkX graph into a human-readable JSON export."""

    payload: dict[str, Any] = {
        "nodes": [],
        "edges": [],
    }
    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        node_payload = paper.to_dict() if isinstance(paper, Paper) else {"id": node_id}
        node_payload["cluster"] = data.get("cluster", -1)
        payload["nodes"].append(node_payload)

    for source, target, data in graph.edges(data=True):
        payload["edges"].append(
            {
                "source": source,
                "target": target,
                "type": data.get("type", "combined"),
                "edge_types": data.get("edge_types", []),
                "weight": data.get("weight", 0.0),
                "reasons": data.get("reasons", []),
                "evidence": data.get("evidence", {}),
            }
        )
    return json.dumps(payload, indent=2)


def graph_to_graphml_bytes(graph: nx.Graph) -> bytes:
    """Serialize a graph to GraphML after converting rich attrs to strings."""

    export_graph = nx.Graph()
    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        if isinstance(paper, Paper):
            attrs = {
                "citekey": paper.citekey,
                "title": paper.title,
                "authors": "; ".join(paper.authors),
                "year": paper.year or "",
                "venue": paper.venue,
                "doi": paper.doi,
                "tags": "; ".join(paper.tags),
                "collections": "; ".join(paper.collections),
                "cluster": data.get("cluster", -1),
            }
        else:
            attrs = {"cluster": data.get("cluster", -1)}
        export_graph.add_node(node_id, **attrs)

    for source, target, data in graph.edges(data=True):
        export_graph.add_edge(
            source,
            target,
            type=data.get("type", "combined"),
            edge_types="; ".join(data.get("edge_types", [])),
            weight=float(data.get("weight", 0.0)),
            reasons="; ".join(data.get("reasons", [])),
        )

    buffer = io.BytesIO()
    nx.write_graphml(export_graph, buffer)
    return buffer.getvalue()


def write_export(filename: str, content: str | bytes) -> Path:
    """Write an export artifact to the local exports folder."""

    ensure_project_dirs()
    path = EXPORTS_DIR / filename
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path
