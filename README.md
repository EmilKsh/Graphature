# Graphature
<img width="1959" height="1108" alt="image" src="https://github.com/user-attachments/assets/522526b8-929e-4e71-9bc5-6eb10a78d569" />

Graphature is a local-first Streamlit app for exploring a personal literature graph of academic papers. It imports your paper library, builds an explainable NetworkX graph, detects clusters, and renders an interactive graph plus a sortable papers table and detail panel.

The project is designed for literature review work where the graph should help you understand why papers are connected, not only display a nice network. Every edge stores human-readable reasons and machine-readable evidence.

## Principles

- Local-first by default
- No API keys required for core functionality
- No database server
- No writes into Zotero's SQLite database
- Useful even when citation metadata is incomplete
- Every visible edge should be explainable

## Quick Start

```bash
cd Graphature
pip install -r requirements.txt
streamlit run app.py
```

The app includes sample BibTeX and manual metadata files, so it can start without your own library.

## Desktop Window

Graphature can also run as a standalone desktop-style window. It still uses the local Streamlit app internally, but a launcher starts the server on a private localhost port and opens it in its own WebView window instead of a browser tab.

Install the requirements, then use either:

```bash
python graphature_desktop.py
```

On Windows, you can also double-click `Graphature.pyw` for a no-console launch, or run:

```bat
Graphature.cmd
```

When the desktop window closes, the launcher stops the Streamlit server. Launcher logs are written to `graphature_project/logs/desktop.log`.

## Repository Layout

```text
Graphature/
  app.py
  graphature_desktop.py
  Graphature.pyw
  Graphature.cmd
  requirements.txt
  README.md
  .streamlit/
    config.toml
  graphature/
    importers.py
    models.py
    graph_builder.py
    clustering.py
    visualization.py
    reference_extraction.py
    search.py
    storage.py
    utils.py
    components/
      vis_graph/
  examples/
    sample_library.bib
    sample_manual_metadata.yaml
  tests/
  graphature_project/
    data/
    exports/
    logs/
    notes/
```

`graphature/` is the Python package. `graphature_project/` is the local working data folder created by the app.

## Local Data and Git

The app keeps personal data in `graphature_project/`:

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

The `.gitignore` keeps local BibTeX, YAML, JSON caches, and exports out of Git while preserving `.gitkeep` files. This is intentional so you can attach the repo to a remote without publishing your Zotero library, PDFs, cache files, or local configuration.

To attach a remote:

```bash
git remote add origin <your-remote-url>
git branch -M main
git push -u origin main
```

## Project Management

Graphature currently manages one local project folder per checkout: `graphature_project/`. The source code lives in the repository root, while imports, caches, exports, and local edits live under that project folder.

Important project files:

- `source_config.json`: remembers the selected source type and local paths, such as your Zotero database path or Better BibTeX export path.
- `papers_cache.json`: stores the normalized imported paper records for quick inspection and reuse.
- `paper_overrides.json`: stores local edits made in Graphature, such as tags, collections, and read status.
- `reference_cache.json`: stores locally extracted PDF reference text so citation graph scans are faster after the first run.
- `exports/`: stores saved graph exports.

The project folder is machine-local state. You can delete cache files if you want Graphature to rebuild them, but keep `paper_overrides.json` if you want to preserve edits made inside the app.

For now, creating a separate project means using a separate checkout or manually swapping the contents of `graphature_project/`. A future version may add named projects inside the UI.

## Import Options

Graphature supports three library sources:

- Upload or sample BibTeX
- Local BibTeX file path, useful with Better BibTeX auto-export
- Direct read-only Zotero SQLite import

For Zotero SQLite import, point the app at `zotero.sqlite`. Graphature creates a temporary local snapshot and reads from that snapshot, so it does not write to Zotero.

Important path rule: local paths are resolved on the machine running the Streamlit server, not in the browser. If Graphature is deployed on another machine, it cannot read `C:\...`, `/Users/...`, Zotero databases, Better BibTeX auto-export files, or PDFs that exist only on your computer. For deployed use, upload BibTeX/manual metadata files. For Zotero SQLite import, auto-export paths, and PDF attachment scanning, run Graphature locally.

## Add a Zotero Database

Graphature can read Zotero directly without modifying Zotero's database. This is intended for local runs, where the Streamlit server and Zotero data directory are on the same machine.

Typical Zotero database locations:

```text
Windows: C:\Users\<you>\Zotero\zotero.sqlite
macOS:   /Users/<you>/Zotero/zotero.sqlite
Linux:   /home/<you>/Zotero/zotero.sqlite
```

If you changed Zotero's data directory, open Zotero and check `Edit -> Settings -> Advanced -> Files and Folders` for the data directory path. The database file is named `zotero.sqlite` inside that directory.

To connect it:

1. Run Graphature with `streamlit run app.py`.
2. Open the `Import` section in the sidebar.
3. Set `Library source` to `Zotero SQLite`.
4. Paste or type the path to `zotero.sqlite`.
5. Click `Load / refresh Zotero library`.

Graphature copies Zotero's SQLite files to a temporary snapshot and reads that copy. This avoids locking issues and keeps Zotero untouched. If your Zotero library changes, click `Load / refresh Zotero library` again.

In a deployed app, a Zotero path from your computer will not work because the deployed server cannot see your filesystem. Use `streamlit run app.py` locally for direct Zotero access, or export/upload BibTeX instead.

Zotero collections are imported with their hierarchy. If a paper is in `Simulation Intelligence / Fundamentals`, selecting `Simulation Intelligence` includes that paper, while coloring by collection can still distinguish the subcollection.

PDF attachments are read only by path. If you choose `Citation graph` or enable `Scan attached PDFs for references`, Graphature scans local attached PDFs with `pypdf` and caches extracted reference sections in `reference_cache.json`.

## Better BibTeX Workflow

1. Install Better BibTeX for Zotero if you want stable citekeys.
2. In Zotero, select your library or a collection.
3. Choose `File -> Export Library...` or right-click a collection and choose `Export Collection...`.
4. Select `Better BibTeX` or `BibTeX`.
5. Save the file.
6. In Graphature, choose `BibTeX file path` and point to the exported `.bib` file.

Better BibTeX auto-export works well because Graphature reloads when the selected BibTeX file changes.

## Manual Metadata

You can add a YAML or JSON companion file keyed by citekey:

```yaml
papers:
  muller2007pbd:
    important_references: ["baraff1996linear", "witkin1997physically"]
    manual_related: ["macklin2016xpbd"]
    notes: "Important because it introduces position based dynamics."
  macklin2016xpbd:
    manual_related: ["muller2007pbd"]
```

Manual metadata is merged into imported records by citekey. Missing fields are fine.

## Graph Edges

Every edge has:

- source and target paper ids
- edge type list
- weight
- human-readable reasons
- evidence fields, such as shared tags, citation match type, or similarity score

Edge weights are additive:

- Same tag: `+1` per shared tag
- Same collection: `+2` per shared collection
- Same author: `+1` per shared author
- Manual relation: `+5`
- Citation/reference match: `+6`
- Title/abstract similarity: `similarity * 4`

Example reason:

```text
same tag: XPBD; same collection: thesis core; title/abstract similarity: 0.78
```

## Citation Graphs

Citation edges are created when a reference mentions another imported paper by:

- citekey
- DOI
- full title
- conservative first-author/year match

Graphature checks reference metadata fields such as `important_references`, `references`, `cites`, `citation`, `citations`, and `bibliography`.

When you choose `Citation graph`, Graphature also scans attached local PDFs for reference sections with `pypdf` and caches extracted reference text in `graphature_project/data/reference_cache.json`. You can also enable PDF scanning in other graph modes from the Import section.

PDF scanning is local. It may take a little while on the first run, but later runs use the cache.

## Graph Controls

`Minimum edge weight` filters edges after all evidence is combined. Use:

- `0-2` for broad exploration
- `3-5` for cleaner conceptual/tag/author graphs
- `6` or lower for citation-only graphs, because a citation edge weighs `6`

`Similarity threshold` controls only title/abstract similarity edges. It is a local cosine similarity over title plus abstract tokens. Use:

- `0.20-0.25` to reveal loose topical neighborhoods
- `0.28-0.35` as a good default range
- `0.40+` for stricter similarity links

If the graph is too dense, raise the minimum edge weight or similarity threshold. If it is too sparse, lower them.

## Interaction

- Drag the graph background to pan.
- Hold `Ctrl` and scroll to zoom the graph.
- Left-click a node to select it.
- Click empty graph space to deselect.
- Hold `Shift` and click to multi-select nodes.
- Hold `Shift` and drag a box to select multiple nodes.
- Sort the papers table by clicking column headers.
- Select papers in either the graph or the papers table to update the detail panel.
- Edit tags, collections, and read status from the detail panel.

## Clustering and Coloring

Graphature uses NetworkX greedy modularity community detection on the weighted graph. Nodes can be colored by:

- detected cluster
- first tag
- publication year decade
- first collection

For Zotero collections, nested collection paths are preserved. Selecting a parent collection includes papers from its subcollections, while subcollections can still receive distinct graph colors.

## Exports

The Export section can download or save:

- interactive HTML graph
- GraphML
- JSON graph

Saved exports go to `graphature_project/exports/`.

## Tests

```bash
python -m pytest -q
```

The tests cover importers, graph construction, search/filter behavior, reference extraction path handling, and local property overrides.

## Current Scope

Implemented:

- BibTeX import
- Better BibTeX file path import
- Direct read-only Zotero SQLite import
- Optional YAML/JSON companion metadata
- Local PDF reference-section scanning
- Explainable weighted graph construction
- Citation graph mode
- Community clustering
- Interactive graph with draggable nodes, panning, Ctrl-scroll zoom, and Shift box selection
- Sortable papers table
- Paper detail panel with editable local properties
- Parent/subcollection filtering for Zotero collections
- HTML, GraphML, and JSON exports
- Sample data and unit tests

Not yet implemented:

- GROBID integration
- Online enrichment with OpenAlex, Crossref, or Semantic Scholar
- Local embeddings
- UMAP/HDBSCAN literature maps
- Obsidian note sync
- Timeline view
- Literature review outline generation

## Roadmap

1. GROBID integration for deeper local PDF metadata/reference extraction.
2. Optional online enrichment.
3. Local semantic embeddings with sentence-transformers.
4. UMAP 2D literature map.
5. HDBSCAN topic clusters.
6. Important reference detection from citation frequency.
7. Obsidian Markdown note integration.
8. Separate concept graph and citation graph layers.
9. Timeline view by publication year.
10. Cluster comparison and bridge-paper detection.
11. Literature review outline generation from clusters.
