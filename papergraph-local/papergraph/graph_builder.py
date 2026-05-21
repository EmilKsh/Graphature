"""Build explainable NetworkX graphs from normalized paper records."""

from __future__ import annotations

import itertools
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

import networkx as nx

from papergraph.models import Edge, Paper
from papergraph.utils import clean_doi, clean_string, compact_key, normalize_key


EDGE_TYPES = [
    "same_tag",
    "same_collection",
    "same_author",
    "title_abstract_similarity",
    "manual_related",
    "cites",
]

GRAPH_MODE_PRESETS: dict[str, list[str]] = {
    "All papers": EDGE_TYPES,
    "My read papers only": EDGE_TYPES,
    "Read papers + important references": EDGE_TYPES,
    "Topic similarity graph": ["title_abstract_similarity", "same_tag", "manual_related"],
    "Tag/collection graph": ["same_tag", "same_collection"],
    "Manual conceptual graph": ["manual_related"],
    "Citation graph": ["cites"],
}


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "using",
    "toward",
    "towards",
    "based",
    "method",
    "methods",
    "simulation",
    "simulations",
}

MIN_TITLE_MATCH_LENGTH = 18
MIN_AUTHOR_SURNAME_LENGTH = 4


@dataclass(frozen=True)
class GraphSettings:
    """Configuration for graph construction."""

    included_edge_types: list[str] = field(default_factory=lambda: list(EDGE_TYPES))
    min_edge_weight: float = 0.0
    similarity_threshold: float = 0.28


def build_graph(papers: Iterable[Paper], settings: GraphSettings | None = None) -> nx.Graph:
    """Build a weighted, explainable literature graph."""

    settings = settings or GraphSettings()
    included = set(settings.included_edge_types or EDGE_TYPES)
    paper_list = list(papers)
    graph = nx.Graph()

    for paper in paper_list:
        graph.add_node(
            paper.id,
            paper=paper,
            citekey=paper.citekey,
            title=paper.title,
            label=paper.label,
            authors=paper.authors,
            year=paper.year,
            tags=paper.tags,
            collections=paper.collections,
            topic_labels=paper.topic_labels,
            abstract=paper.abstract,
            notes=paper.notes_content,
            cluster=-1,
        )

    edges: dict[tuple[str, str], Edge] = {}

    if {"same_tag", "same_collection", "same_author", "title_abstract_similarity"} & included:
        _add_pairwise_edges(paper_list, edges, included, settings.similarity_threshold)

    if "manual_related" in included:
        _add_reference_list_edges(
            paper_list,
            edges,
            attribute="manual_related",
            edge_type="manual_related",
            weight=5.0,
            reason_template="{source} is manually related to {target}",
        )

    if "cites" in included:
        _add_reference_list_edges(
            paper_list,
            edges,
            attribute="important_references",
            edge_type="cites",
            weight=6.0,
            reason_template="{source} cites/references {target}",
        )

    for edge in edges.values():
        if edge.weight < settings.min_edge_weight:
            continue
        graph.add_edge(edge.source, edge.target, **edge.to_dict())

    return graph


def edge_explanations_for_paper(graph: nx.Graph, paper_id: str) -> list[dict[str, object]]:
    """Return connected-paper rows with weights and reasons for one paper."""

    if paper_id not in graph:
        return []

    rows: list[dict[str, object]] = []
    for neighbor in graph.neighbors(paper_id):
        data = graph.edges[paper_id, neighbor]
        paper = graph.nodes[neighbor].get("paper")
        rows.append(
            {
                "Connected paper": getattr(paper, "title", neighbor) or getattr(paper, "citekey", neighbor),
                "Citekey": getattr(paper, "citekey", ""),
                "Year": getattr(paper, "year", None),
                "Edge weight": round(float(data.get("weight", 0.0)), 2),
                "Reasons": "; ".join(data.get("reasons", [])),
            }
        )
    return sorted(rows, key=lambda row: float(row["Edge weight"]), reverse=True)


def _add_pairwise_edges(
    papers: list[Paper],
    edges: dict[tuple[str, str], Edge],
    included: set[str],
    similarity_threshold: float,
) -> None:
    similarities = _text_similarities(papers) if "title_abstract_similarity" in included else {}

    for left, right in itertools.combinations(papers, 2):
        left_tags = _normalized_set(left.tags)
        right_tags = _normalized_set(right.tags)
        shared_tags = sorted(left_tags & right_tags)
        if shared_tags and "same_tag" in included:
            display = _display_matches(shared_tags, [*left.tags, *right.tags])
            weight = float(len(shared_tags))
            reason = _plural_reason("same tag", "same tags", display)
            _add_edge(edges, left, right, "same_tag", weight, reason, {"shared_tags": display})

        left_collections = _normalized_set(left.collections)
        right_collections = _normalized_set(right.collections)
        shared_collections = sorted(left_collections & right_collections)
        if shared_collections and "same_collection" in included:
            display = _display_matches(shared_collections, [*left.collections, *right.collections])
            weight = 2.0 * len(shared_collections)
            reason = _plural_reason("same collection", "same collections", display)
            _add_edge(
                edges,
                left,
                right,
                "same_collection",
                weight,
                reason,
                {"shared_collections": display},
            )

        left_authors = _normalized_set(left.authors)
        right_authors = _normalized_set(right.authors)
        shared_authors = sorted(left_authors & right_authors)
        if shared_authors and "same_author" in included:
            display = _display_matches(shared_authors, [*left.authors, *right.authors])
            weight = float(len(shared_authors))
            reason = _plural_reason("same author", "same authors", display)
            _add_edge(edges, left, right, "same_author", weight, reason, {"shared_authors": display})

        similarity = similarities.get((left.id, right.id), 0.0)
        if similarity >= similarity_threshold and "title_abstract_similarity" in included:
            weight = round(similarity * 4.0, 3)
            reason = f"title/abstract similarity: {similarity:.2f}"
            _add_edge(
                edges,
                left,
                right,
                "title_abstract_similarity",
                weight,
                reason,
                {"similarity_score": round(similarity, 4)},
            )


def _add_reference_list_edges(
    papers: list[Paper],
    edges: dict[tuple[str, str], Edge],
    attribute: str,
    edge_type: str,
    weight: float,
    reason_template: str,
) -> None:
    by_citekey = {normalize_key(paper.citekey): paper for paper in papers if paper.citekey}
    by_title = {compact_key(paper.title): paper for paper in papers if paper.title}
    by_doi = {normalize_key(clean_doi(paper.doi)): paper for paper in papers if clean_doi(paper.doi)}

    for source in papers:
        references = getattr(source, attribute)
        seen_targets: set[str] = set()
        for reference in references:
            for target, match_type in _resolve_reference_matches(reference, papers, by_citekey, by_title, by_doi):
                if target.id == source.id or target.id in seen_targets:
                    continue
                seen_targets.add(target.id)
                reason = reason_template.format(source=source.citekey, target=target.citekey)
                if edge_type == "cites":
                    reason = f"{source.citekey} cites/references {target.citekey} ({match_type} match)"
                _add_edge(
                    edges,
                    source,
                    target,
                    edge_type,
                    weight,
                    reason,
                    {
                        edge_type: [
                            {
                                "source": source.citekey,
                                "target": target.citekey,
                                "match": _short_reference_text(reference),
                                "match_type": match_type,
                            }
                        ]
                    },
                )


def _resolve_reference_matches(
    reference: str,
    candidates: list[Paper],
    by_citekey: dict[str, Paper],
    by_title: dict[str, Paper],
    by_doi: dict[str, Paper],
) -> list[tuple[Paper, str]]:
    """Find all imported papers mentioned by one reference string."""

    normalized_reference = normalize_key(reference)
    compact_reference = compact_key(reference)
    doi_reference = normalize_key(clean_doi(reference))
    matches: list[tuple[Paper, str]] = []
    seen_ids: set[str] = set()

    def add_match(paper: Paper | None, match_type: str) -> None:
        if not paper or paper.id in seen_ids:
            return
        seen_ids.add(paper.id)
        matches.append((paper, match_type))

    add_match(by_citekey.get(normalized_reference), "citekey")
    add_match(by_title.get(compact_reference), "title")
    add_match(by_doi.get(doi_reference), "doi")

    for paper in candidates:
        if paper.id in seen_ids:
            continue
        if _reference_mentions_citekey(normalized_reference, paper.citekey):
            add_match(paper, "citekey")
            continue
        if _reference_mentions_doi(normalized_reference, doi_reference, paper.doi):
            add_match(paper, "doi")
            continue
        if _reference_mentions_title(compact_reference, paper.title):
            add_match(paper, "title")
            continue
        if _reference_mentions_author_year(reference, paper):
            add_match(paper, "author-year")

    return matches


def _resolve_reference(
    reference: str,
    by_citekey: dict[str, Paper],
    by_title: dict[str, Paper],
) -> Paper | None:
    """Resolve one reference for compatibility with older call sites."""

    candidates = {paper.id: paper for paper in [*by_citekey.values(), *by_title.values()]}
    matches = _resolve_reference_matches(reference, list(candidates.values()), by_citekey, by_title, {})
    return matches[0][0] if matches else None


def _reference_mentions_citekey(normalized_reference: str, citekey: str) -> bool:
    key = normalize_key(citekey)
    if not key:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])"
    return bool(re.search(pattern, normalized_reference))


def _reference_mentions_doi(normalized_reference: str, doi_reference: str, doi: str) -> bool:
    target = normalize_key(clean_doi(doi))
    if len(target) < 6:
        return False
    return target in normalized_reference or target in doi_reference


def _reference_mentions_title(compact_reference: str, title: str) -> bool:
    title_key = compact_key(title)
    return len(title_key) >= MIN_TITLE_MATCH_LENGTH and title_key in compact_reference


def _reference_mentions_author_year(reference: str, paper: Paper) -> bool:
    if not paper.year or not paper.authors:
        return False

    surname = _first_author_surname(paper.authors[0])
    if len(surname) < MIN_AUTHOR_SURNAME_LENGTH:
        return False

    folded_reference = _fold_text(reference)
    if str(paper.year) not in folded_reference:
        return False

    pattern = rf"(?<![a-z0-9]){re.escape(surname)}(?![a-z0-9])"
    return bool(re.search(pattern, folded_reference))


def _first_author_surname(author: str) -> str:
    text = _fold_text(author)
    if "," in text:
        return text.split(",", 1)[0].strip()
    parts = [part for part in re.split(r"\s+", text) if part]
    return parts[-1] if parts else ""


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_string(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _short_reference_text(reference: str, limit: int = 220) -> str:
    text = clean_string(reference)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _add_edge(
    edges: dict[tuple[str, str], Edge],
    left: Paper,
    right: Paper,
    edge_type: str,
    weight: float,
    reason: str,
    evidence: dict[str, object],
) -> None:
    source, target = sorted([left.id, right.id])
    key = (source, target)
    if key not in edges:
        edges[key] = Edge(source=source, target=target)
    edges[key].add_evidence(edge_type, weight, reason, evidence)


def _normalized_set(values: Iterable[str]) -> set[str]:
    return {normalize_key(value) for value in values if normalize_key(value)}


def _display_matches(keys: Iterable[str], candidates: list[str]) -> list[str]:
    display: list[str] = []
    for key in keys:
        value = next((candidate for candidate in candidates if normalize_key(candidate) == key), key)
        if value not in display:
            display.append(value)
    return display


def _plural_reason(singular: str, plural: str, values: list[str]) -> str:
    label = singular if len(values) == 1 else plural
    return f"{label}: {', '.join(values)}"


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", text.lower())
    return [token for token in tokens if token not in STOPWORDS]


def _text_similarities(papers: list[Paper]) -> dict[tuple[str, str], float]:
    documents = {paper.id: _tokenize(f"{paper.title} {paper.abstract}") for paper in papers}
    document_frequency: dict[str, int] = {}
    for tokens in documents.values():
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    total_docs = max(len(documents), 1)
    vectors: dict[str, dict[str, float]] = {}
    norms: dict[str, float] = {}
    for paper_id, tokens in documents.items():
        term_counts: dict[str, int] = {}
        for token in tokens:
            term_counts[token] = term_counts.get(token, 0) + 1

        vector: dict[str, float] = {}
        for token, count in term_counts.items():
            idf = math.log((1 + total_docs) / (1 + document_frequency[token])) + 1.0
            vector[token] = count * idf
        vectors[paper_id] = vector
        norms[paper_id] = math.sqrt(sum(value * value for value in vector.values()))

    similarities: dict[tuple[str, str], float] = {}
    for left, right in itertools.combinations(papers, 2):
        left_vector = vectors[left.id]
        right_vector = vectors[right.id]
        left_norm = norms[left.id]
        right_norm = norms[right.id]
        if not left_vector or not right_vector or left_norm == 0 or right_norm == 0:
            continue
        shared_tokens = set(left_vector) & set(right_vector)
        dot = sum(left_vector[token] * right_vector[token] for token in shared_tokens)
        similarities[(left.id, right.id)] = dot / (left_norm * right_norm)
    return similarities
