"""Core data models for Graphature."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return an ISO timestamp suitable for local cache files."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Paper:
    """A normalized paper record imported from BibTeX and optional metadata."""

    id: str
    citekey: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    abstract: str = ""
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    file_path: str | None = None
    read_status: bool = True
    notes_path: str | None = None
    notes_content: str = ""
    important_references: list[str] = field(default_factory=list)
    manual_related: list[str] = field(default_factory=list)
    topic_labels: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    modified_at: str = field(default_factory=utc_now_iso)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Short label for graph nodes."""

        first_author = self.authors[0].split(",")[0].strip() if self.authors else ""
        if first_author and self.year:
            return f"{first_author} {self.year}"
        if self.year:
            return f"{self.citekey} ({self.year})"
        return self.citekey or self.title[:32] or self.id

    def searchable_text(self) -> str:
        """Return a combined text blob for simple local search."""

        fields = [
            self.citekey,
            self.title,
            " ".join(self.authors),
            str(self.year or ""),
            self.venue,
            self.doi,
            self.abstract,
            " ".join(self.tags),
            " ".join(self.collections),
            self.notes_content,
            " ".join(self.topic_labels),
        ]
        return " ".join(part for part in fields if part).lower()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Paper":
        """Create a Paper from cache data."""

        return cls(**data)


@dataclass(slots=True)
class Edge:
    """An explainable relationship between two papers."""

    source: str
    target: str
    type: str = "combined"
    weight: float = 0.0
    reasons: list[str] = field(default_factory=list)
    edge_types: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def add_evidence(
        self,
        edge_type: str,
        weight: float,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Add one piece of evidence to this edge."""

        self.weight = round(self.weight + weight, 4)
        if edge_type not in self.edge_types:
            self.edge_types.append(edge_type)
        self.type = edge_type if len(self.edge_types) == 1 else "combined"
        if reason and reason not in self.reasons:
            self.reasons.append(reason)
        if evidence:
            for key, value in evidence.items():
                if key not in self.evidence:
                    self.evidence[key] = value
                    continue
                current = self.evidence[key]
                if isinstance(current, list):
                    values = value if isinstance(value, list) else [value]
                    for item in values:
                        if item not in current:
                            current.append(item)
                elif current != value:
                    self.evidence[key] = [current, value]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""

        return asdict(self)
