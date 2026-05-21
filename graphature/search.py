"""Search and filtering helpers."""

from __future__ import annotations

from collections.abc import Iterable

from graphature.models import Paper
from graphature.utils import normalize_key


def search_papers(papers: Iterable[Paper], query: str) -> list[Paper]:
    """Search papers across title, authors, year, citekey, tags, abstract, and notes."""

    terms = [normalize_key(term) for term in query.split() if normalize_key(term)]
    paper_list = list(papers)
    if not terms:
        return paper_list
    return [paper for paper in paper_list if all(term in paper.searchable_text() for term in terms)]


def filter_papers(
    papers: Iterable[Paper],
    tags: list[str] | None = None,
    authors: list[str] | None = None,
    collections: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
) -> list[Paper]:
    """Filter papers by selected facets."""

    selected_tags = {normalize_key(tag) for tag in tags or []}
    selected_authors = {normalize_key(author) for author in authors or []}
    selected_collections = {normalize_key(collection) for collection in collections or []}

    results: list[Paper] = []
    for paper in papers:
        if selected_tags and not selected_tags.intersection({normalize_key(tag) for tag in paper.tags}):
            continue
        if selected_authors and not selected_authors.intersection({normalize_key(author) for author in paper.authors}):
            continue
        if selected_collections and not selected_collections.intersection(_collection_filter_keys(paper.collections)):
            continue
        if year_range and paper.year and not (year_range[0] <= paper.year <= year_range[1]):
            continue
        if year_range and paper.year is None:
            continue
        results.append(paper)
    return results


def available_facets(papers: Iterable[Paper]) -> dict[str, list]:
    """Return sorted tag, author, collection, and year options."""

    tags: set[str] = set()
    authors: set[str] = set()
    collections: set[str] = set()
    years: set[int] = set()
    for paper in papers:
        tags.update(paper.tags)
        authors.update(paper.authors)
        for collection in paper.collections:
            collections.update(_collection_facets(collection))
        if paper.year:
            years.add(paper.year)
    return {
        "tags": sorted(tags, key=str.lower),
        "authors": sorted(authors, key=str.lower),
        "collections": sorted(collections, key=str.lower),
        "years": sorted(years),
    }


def _collection_filter_keys(collections: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for collection in collections:
        keys.update(normalize_key(value) for value in _collection_facets(collection))
    return keys


def _collection_facets(collection: str) -> list[str]:
    parts = [part.strip() for part in collection.split("/") if part.strip()]
    if not parts:
        return []
    return [" / ".join(parts[:index]) for index in range(1, len(parts) + 1)]
