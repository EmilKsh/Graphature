# Graphature

Graphature is a local-first Streamlit app for building an explainable graph of papers you have read. It imports a BibTeX library, optionally merges manual YAML/JSON metadata, builds a NetworkX graph, detects communities, and renders an interactive selectable graph.

The MVP works offline from exported metadata. It does not require API keys, cloud services, a database server, or writes into Zotero's SQLite database. Optional local PDF scanning can help recover reference links when exported metadata does not include a bibliography.

## Install

```bash
cd Graphature
pip install -r requirements.txt
streamlit run app.py
```

The app includes sample data, so it opens with a small computational mechanics literature graph if you have not uploaded your own files yet.

## Export BibTeX From Zotero

1. Install Better BibTeX for Zotero if you want stable citekeys.
2. In Zotero, select a collection or your read-paper library.
3. Choose `File -> Export Library...` or right-click a collection and choose `Export Collection...`.
4. Select `Better BibTeX` or `BibTeX`.
5. Save the file and either upload it in the app sidebar or set the Better BibTeX auto-export path as the library source.

Better BibTeX citekeys become the stable merge key for manual metadata.

You can also select `Zotero SQLite` in the sidebar and point Graphature at `zotero.sqlite`. The database is opened read-only.

## Manual Metadata

You can add a YAML or JSON file keyed by citekey:

```yaml
papers:
  muller2007pbd:
    important_references: ["baraff1996linear", "witkin1997physically"]
    manual_related: ["macklin2016xpbd"]
    notes: "Important because it introduces position based dynamics."
```

Manual metadata is merged into imported BibTeX records by citekey. Missing fields are fine.

## How Edges Are Created

Every visible edge stores a weight, edge type list, machine-readable evidence, and human-readable reasons.

Weights:

- Same tag: `+1` per shared tag
- Same collection: `+2` per shared collection
- Same author: `+1` per shared author
- Manual relation: `+5`
- Citation or important reference match: `+6`
- Title/abstract similarity: `similarity * 4`

Example reason:

```text
same tag: XPBD; same collection: thesis core; title/abstract similarity: 0.78
```

Citation edges scan reference metadata already present locally, such as `important_references`, `references`, `cites`, `citation`, `citations`, or `bibliography`. If a reference mentions another imported paper by citekey, DOI, full title, or a conservative first-author/year match, Graphature adds a `cites` edge and records the match type as evidence. If you enable PDF scanning, Graphature also extracts local PDF reference sections with `pypdf` and caches the result.

## Clustering

The MVP uses NetworkX greedy modularity community detection on the weighted graph. Cluster ids are assigned to nodes and can be used as graph colors. You can also color nodes by first tag, year decade, or first collection.

## Local Project Folder

The app creates:

```text
graphature_project/
  data/
    library.bib
    manual_metadata.yaml
    papers_cache.json
    paper_overrides.json
    reference_cache.json
    source_config.json
  exports/
    graph.html
    graph.graphml
    graph.json
  notes/
```

Uploaded files are copied into `graphature_project/data/`. The app can download or save the current graph as HTML, GraphML, and JSON.

Local edits made in the app, such as tags, collections, and read status, are stored in `paper_overrides.json` and reapplied after each import.

## Current MVP Scope

Implemented:

- BibTeX import
- Better BibTeX auto-export path import
- Direct read-only Zotero SQLite import
- Optional YAML/JSON companion metadata
- Optional local PDF reference-section scanning
- Local paper schema
- Explainable NetworkX graph construction
- Community clustering
- Interactive vis-network graph with panning, draggable nodes, and Shift+drag box selection
- Streamlit UI with imports, graph settings, filters, search, graph/table selection, paper details, editable tags/properties, edge explanation table, and exports
- Papers table with native column-header sorting
- All-papers graph mode plus read-paper filtering for the read-only mode
- Sample BibTeX/YAML data
- Unit tests for importing, graph building, and local property overrides

Not yet implemented:

- Local PDF parsing with GROBID
- Online enrichment
- Local embeddings
- UMAP/HDBSCAN views

Select papers in the graph or papers list to populate the detail panel and edge explanation table.

## Roadmap

1. GROBID integration for deeper local PDF metadata/reference extraction.
2. Optional enrichment using OpenAlex, Crossref, or Semantic Scholar.
3. Local semantic embeddings using sentence-transformers.
4. UMAP 2D literature map.
5. HDBSCAN topic clusters.
6. Important reference detection from citation frequency.
7. Obsidian Markdown note integration.
8. Concept graph separate from citation graph.
9. Timeline view by publication year.
10. Compare clusters and find bridge papers.
11. Generate literature review outlines from clusters.
