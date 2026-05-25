"""Streamlit interface for Graphature."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

from graphature.clustering import assign_communities, cluster_summary
from graphature.graph_builder import (
    EDGE_TYPES,
    GRAPH_MODE_PRESETS,
    GraphSettings,
    build_graph,
    edge_explanations_for_paper,
)
from graphature.importers import merge_manual_metadata, parse_bibtex_text, parse_manual_metadata_text, parse_zotero_sqlite
from graphature.reference_extraction import enrich_references_from_local_pdfs
from graphature.search import available_facets, filter_papers, search_papers
from graphature.storage import (
    apply_paper_overrides,
    ensure_project_dirs,
    graph_to_graphml_bytes,
    graph_to_json,
    load_source_config,
    load_paper_overrides,
    save_papers_cache,
    save_source_config,
    save_uploaded_text,
    update_paper_overrides,
    write_export,
)
from graphature.utils import ensure_list, normalize_key, unique_clean_strings
from graphature.visualization import generate_pyvis_html, graph_color_legend, graph_to_vis_data


ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "graphature" / "assets"
LOGO_ICON = ASSETS_DIR / "graphature_icon.png"
LOGO_APP_ICON = ASSETS_DIR / "graphature_app_icon.png"
SAMPLE_BIB = ROOT / "examples" / "sample_library.bib"
SAMPLE_MANUAL = ROOT / "examples" / "sample_manual_metadata.yaml"
VIS_GRAPH = components.declare_component(
    "graphature_vis_graph_v2",
    path=str(ROOT / "graphature" / "components" / "vis_graph" / "frontend"),
)
GRAPH_VISUAL_VERSION = "theme-sync-v1"
DEFAULT_GRAPH_THEME = "light"
THEME_OPTIONS = {
    "Light": "light",
    "Dark": "dark",
    "System": "system",
}


EDGE_LABELS = {
    "same_tag": "Same tag",
    "same_collection": "Same collection",
    "same_author": "Same author",
    "title_abstract_similarity": "Title/abstract similarity",
    "manual_related": "Manual related",
    "cites": "Cites / reference match",
}


def main() -> None:
    page_icon = _page_icon()
    if page_icon is None:
        st.set_page_config(page_title="Graphature", layout="wide")
    else:
        st.set_page_config(page_title="Graphature", page_icon=page_icon, layout="wide")
    ensure_project_dirs()
    _init_state()
    graph_theme = _active_theme()
    _inject_css(graph_theme)
    _app_title()
    _sidebar_theme_control()

    source = _sidebar_imports()
    if source["source_kind"] == "zotero_pending":
        st.info("Choose a Zotero SQLite path, then click **Load / refresh Zotero library** in the sidebar.")
        return
    if not source["bib_text"].strip() and not source["zotero_path"]:
        st.info("Upload a BibTeX file, choose a local BibTeX path, connect Zotero, or enable the sample library.")
        return

    source_fingerprint = _source_fingerprint(source)
    if st.session_state.source_fingerprint != source_fingerprint:
        st.session_state.source_fingerprint = source_fingerprint
        st.session_state.selected_paper_ids = []

    try:
        if source["source_kind"] == "zotero":
            with st.spinner("Reading Zotero library from a local snapshot..."):
                papers = _load_zotero_papers_cached(source["zotero_path"], _file_signature_key(source["zotero_path"]))
            st.sidebar.caption(f"Loaded {len(papers)} Zotero items.")
            if not papers:
                st.sidebar.warning(
                    "This Zotero database opened successfully, but no paper items were found. "
                    "Check that the path points to the active Zotero profile, not an empty database."
                )
        else:
            papers = _parse_bibtex_cached(source["bib_text"])
        manual_text = source["manual_text"]
        manual_metadata = parse_manual_metadata_text(manual_text) if manual_text.strip() else {}
        papers = merge_manual_metadata(papers, manual_metadata)
        papers = apply_paper_overrides(papers, load_paper_overrides())
    except Exception as exc:  # noqa: BLE001
        st.error(f"Import failed: {exc}")
        return

    facets = available_facets(papers)
    settings, filters, color_mode, selected_mode, graph_panel, export_panel = _sidebar_controls(facets)
    if _should_scan_references(source, selected_mode):
        with st.spinner("Scanning local PDFs for citation links..."):
            papers, reference_report = enrich_references_from_local_pdfs(papers)
        _reference_scan_status(reference_report, graph_panel)
    save_papers_cache(papers)

    visible_papers = filter_papers(
        papers,
        tags=filters["tags"],
        authors=filters["authors"],
        collections=filters["collections"],
        year_range=filters["year_range"],
    )
    visible_papers = search_papers(visible_papers, filters["query"])
    if selected_mode == "My read papers only":
        visible_papers = [paper for paper in visible_papers if paper.read_status]

    graph = assign_communities(build_graph(visible_papers, settings))
    selected_ids = _valid_selected_ids(graph)
    graph_data = graph_to_vis_data(
        graph,
        color_mode=color_mode,
        selected_paper_ids=selected_ids,
        graph_theme=graph_theme,
    )
    legend_rows = graph_color_legend(graph, color_mode=color_mode, graph_theme=graph_theme)
    legend_title = "Collection legend" if color_mode == "collection" else "Color legend"
    graph_key = _graph_key(graph, color_mode, graph_theme)

    left, right = st.columns([0.76, 0.24], gap="small")
    with left:
        graph_event = VIS_GRAPH(
            nodes=graph_data["nodes"],
            edges=graph_data["edges"],
            legend=legend_rows,
            legend_title=legend_title,
            selected_ids=selected_ids,
            graph_key=graph_key,
            theme=graph_theme,
            height=532,
            fill_viewport=True,
            viewport_scale=0.7,
            min_height=392,
            bottom_margin=14,
            key=f"vis_graph_{source_fingerprint[:12]}",
            default={"selected_ids": selected_ids},
        )
        graph_selected = _node_ids_from_graph_event(graph_event, graph)
        if graph_selected != selected_ids:
            _set_selected_ids(graph_selected)

        table_selected = _papers_list(graph, selected_mode, source_fingerprint, graph_theme)
        if table_selected:
            _set_selected_ids(table_selected)

        selected_ids = _valid_selected_ids(graph)
        selected_paper_id = selected_ids[0] if selected_ids else None
        _downloads(
            graph,
            generate_pyvis_html(graph, color_mode=color_mode, selected_paper_id=selected_paper_id),
            export_panel,
        )

    selected_ids = _valid_selected_ids(graph)
    selected_paper_id = selected_ids[0] if selected_ids else None
    with right:
        st.markdown('<div class="detail-panel-anchor" aria-hidden="true">&nbsp;</div>', unsafe_allow_html=True)
        _paper_detail(graph, selected_paper_id, selected_ids, facets, graph_theme)


def _init_state() -> None:
    if "selected_paper_ids" not in st.session_state:
        st.session_state.selected_paper_ids = []
    if "source_fingerprint" not in st.session_state:
        st.session_state.source_fingerprint = ""
    if "zotero_loaded_path" not in st.session_state:
        st.session_state.zotero_loaded_path = ""


def _page_icon():
    if not LOGO_APP_ICON.exists():
        return None
    with Image.open(LOGO_APP_ICON) as image:
        return image.copy()


def _active_theme() -> str:
    """Return the active app theme type, defaulting to light."""

    preference = normalize_key(load_source_config().get("theme_preference") or DEFAULT_GRAPH_THEME)
    if preference in {"light", "dark"}:
        return preference

    theme_type = ""
    try:
        theme_type = str(st.context.theme.get("type") or "")
    except Exception:  # noqa: BLE001
        theme_type = ""

    if normalize_key(theme_type) in {"light", "dark"}:
        return normalize_key(theme_type)

    configured = normalize_key(st.get_option("theme.base") or DEFAULT_GRAPH_THEME)
    return configured if configured in {"light", "dark"} else DEFAULT_GRAPH_THEME


def _source_fingerprint(source: dict[str, Any]) -> str:
    payload = {
        "source_kind": source.get("source_kind"),
        "source_label": source.get("source_label"),
        "bib_text": source.get("bib_text"),
        "manual_text": source.get("manual_text"),
        "zotero_path": source.get("zotero_path"),
        "zotero_signature": _file_signature(source.get("zotero_path")),
        "scan_pdfs": source.get("scan_pdfs"),
    }
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sidebar_imports() -> dict[str, Any]:
    import_panel = st.sidebar.expander("Import", expanded=True)

    config = load_source_config()
    source_options = ["Upload / sample", "BibTeX file path", "Zotero SQLite"]
    default_source = "Upload / sample"
    if config.get("bibtex_path"):
        default_source = "BibTeX file path"
    if config.get("zotero_path"):
        default_source = "Zotero SQLite"

    source_kind = import_panel.selectbox(
        "Library source",
        source_options,
        index=source_options.index(config.get("source_kind", default_source))
        if config.get("source_kind", default_source) in source_options
        else 0,
    )
    bib_path = ""
    zotero_path = ""
    bib_upload = None
    use_sample = False

    if source_kind == "Upload / sample":
        bib_upload = import_panel.file_uploader("BibTeX library", type=["bib", "bibtex", "txt"])
        use_sample = import_panel.checkbox("Use sample data", value=bib_upload is None)
    elif source_kind == "BibTeX file path":
        bib_path = import_panel.text_input(
            "Better BibTeX auto-export path",
            value=str(config.get("bibtex_path", "")),
            placeholder=r"C:\Users\you\Zotero\exports\library.bib",
            help="Local paths are read by the Streamlit server. In a deployed app, upload the BibTeX file instead.",
        )
    else:
        zotero_path = import_panel.text_input(
            "Zotero SQLite path",
            value=str(config.get("zotero_path") or _default_zotero_path()),
            placeholder=r"C:\Users\you\Zotero\zotero.sqlite",
            help="Only works when Graphature runs on the same machine as Zotero. Deployed apps cannot read your browser machine's local paths.",
        )
        import_panel.caption("Zotero is read from a temporary local copy. Selecting this source does not load it yet.")

    manual_upload = import_panel.file_uploader("Manual metadata", type=["yaml", "yml", "json", "txt"])
    manual_path = import_panel.text_input(
        "Manual metadata path",
        value=str(config.get("manual_path", "")),
        placeholder=r"C:\path\manual_metadata.yaml",
        help="Local paths are read by the Streamlit server. In a deployed app, upload the metadata file instead.",
    )
    scan_pdfs = import_panel.checkbox(
        "Scan attached PDFs for references",
        value=bool(config.get("scan_pdfs", False)),
        help="Uses PDFs reachable from the Streamlit server. Deployed apps cannot scan PDFs stored only on your computer.",
    )

    bib_text = ""
    manual_text = ""
    source_label = source_kind

    if bib_upload is not None:
        bib_text = bib_upload.getvalue().decode("utf-8", errors="replace")
        save_uploaded_text("library.bib", bib_text)
        source_label = bib_upload.name
    elif source_kind == "BibTeX file path" and bib_path.strip():
        bib_file = _local_path_from_input(bib_path)
        if bib_file.exists():
            bib_text = bib_file.read_text(encoding="utf-8", errors="replace")
            source_label = str(bib_file)
        else:
            import_panel.warning(_server_path_missing_message("BibTeX", bib_file))
    elif use_sample and SAMPLE_BIB.exists():
        bib_text = SAMPLE_BIB.read_text(encoding="utf-8")
        source_label = "Sample data"

    if source_kind == "Zotero SQLite" and zotero_path.strip():
        zotero_file = _local_path_from_input(zotero_path, default_filename="zotero.sqlite")
        if zotero_file.exists() and zotero_file.is_file():
            source_label = str(zotero_file)
            if _clean_local_path_text(zotero_path) != str(zotero_file):
                import_panel.caption(f"Resolved database file: {zotero_file}")
            if import_panel.button("Load / refresh Zotero library", type="primary"):
                st.session_state.zotero_loaded_path = _path_key(zotero_file)
                _load_zotero_papers_cached.clear()
        else:
            import_panel.warning(_server_path_missing_message("Zotero SQLite", zotero_file))

    if manual_upload is not None:
        manual_text = manual_upload.getvalue().decode("utf-8", errors="replace")
        suffix = Path(manual_upload.name).suffix or ".yaml"
        save_uploaded_text(f"manual_metadata{suffix}", manual_text)
    elif manual_path.strip():
        metadata_file = _local_path_from_input(manual_path)
        if metadata_file.exists():
            manual_text = metadata_file.read_text(encoding="utf-8", errors="replace")
        else:
            import_panel.warning(_server_path_missing_message("Manual metadata", metadata_file))
    elif use_sample and SAMPLE_MANUAL.exists():
        manual_text = SAMPLE_MANUAL.read_text(encoding="utf-8")

    zotero_loaded = (
        source_kind == "Zotero SQLite"
        and zotero_path.strip()
        and st.session_state.get("zotero_loaded_path")
        == _path_key(_local_path_from_input(zotero_path, default_filename="zotero.sqlite"))
    )

    _save_source_config_update(
        {
            "source_kind": source_kind,
            "bibtex_path": bib_path.strip(),
            "zotero_path": _clean_local_path_text(zotero_path),
            "manual_path": manual_path.strip(),
            "scan_pdfs": scan_pdfs,
        }
    )

    return {
        "source_kind": "zotero" if zotero_loaded else "zotero_pending" if source_kind == "Zotero SQLite" else "bibtex",
        "source_label": source_label,
        "bib_text": bib_text,
        "manual_text": manual_text,
        "zotero_path": str(_local_path_from_input(zotero_path, default_filename="zotero.sqlite"))
        if zotero_loaded
        else "",
        "scan_pdfs": scan_pdfs,
    }


def _app_title() -> None:
    logo = _image_data_uri(LOGO_ICON)
    logo_markup = (
        f'<span class="app-brand-logo-wrap"><img class="app-brand-logo" src="{logo}" alt="Graphature logo"></span>'
        if logo
        else ""
    )
    st.sidebar.markdown(
        f"""
        <div class="app-brand-row">
            {logo_markup}
            <div class="app-brand-copy">
                <div class="app-brand">Graphature</div>
                <div class="app-brand-subtitle">Local literature graph</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _image_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _clean_local_path_text(value: object) -> str:
    """Normalize pasted local path strings from text inputs."""

    text = str(value or "").strip().strip("\"'`“”‘’")
    if not text:
        return ""

    parsed = urlparse(text)
    if parsed.scheme.lower() == "file":
        if parsed.netloc:
            text = f"//{parsed.netloc}{unquote(parsed.path)}"
        else:
            text = unquote(parsed.path)
        if len(text) >= 3 and text[0] == "/" and text[2] == ":":
            text = text[1:]
    return text.strip().strip("\"'`“”‘’")


def _local_path_from_input(value: object, default_filename: str | None = None) -> Path:
    path = Path(_clean_local_path_text(value)).expanduser()
    if default_filename and path.exists() and path.is_dir():
        return path / default_filename
    return path


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _sidebar_theme_control() -> None:
    config = load_source_config()
    current = normalize_key(config.get("theme_preference") or DEFAULT_GRAPH_THEME)
    if current not in set(THEME_OPTIONS.values()):
        current = DEFAULT_GRAPH_THEME

    label_by_value = {value: label for label, value in THEME_OPTIONS.items()}
    selected_label = st.sidebar.selectbox(
        "Theme",
        list(THEME_OPTIONS),
        index=list(THEME_OPTIONS).index(label_by_value[current]),
        help="Graphature's own theme switcher. System follows Streamlit/browser theme when available.",
    )
    selected = THEME_OPTIONS[selected_label]
    if selected != current:
        _save_source_config_update({"theme_preference": selected})
        st.rerun()


def _default_zotero_path() -> str:
    candidate = Path.home() / "Zotero" / "zotero.sqlite"
    return str(candidate) if candidate.exists() else ""


def _save_source_config_update(updates: dict[str, Any]) -> None:
    config = load_source_config()
    config.update(updates)
    save_source_config(config)


def _server_path_missing_message(kind: str, path: Path) -> str:
    return (
        f"{kind} path was not found on the machine running Graphature: {path}. "
        "If this is a deployed app, it cannot read local paths from your computer through the browser. "
        "Upload the file instead, or run Graphature locally on the machine that has access to that path."
    )


def _file_signature(path_value: object) -> dict[str, object] | None:
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser()
    if not path.exists():
        return None
    stat = path.stat()
    return {"path": str(path), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _file_signature_key(path_value: object) -> str:
    signature = _file_signature(path_value)
    return json.dumps(signature, sort_keys=True, default=str)


@st.cache_data(show_spinner=False)
def _parse_bibtex_cached(bib_text: str):
    return parse_bibtex_text(bib_text)


@st.cache_data(show_spinner=False)
def _load_zotero_papers_cached(zotero_path: str, signature_key: str):
    return parse_zotero_sqlite(zotero_path)


def _reference_scan_status(report: dict[str, Any], panel: Any | None = None) -> None:
    target = panel or st.sidebar
    if not report.get("enabled"):
        if report.get("papers_with_pdf"):
            target.caption(str(report.get("reason", "")))
        return
    target.caption(
        "PDF reference scan: "
        f"{report.get('with_reference_text', 0)} reference sections from "
        f"{report.get('scanned', 0)} local PDFs."
    )


def _should_scan_references(source: dict[str, Any], selected_mode: str) -> bool:
    return bool(source.get("scan_pdfs")) or selected_mode == "Citation graph"


def _sidebar_controls(
    facets: dict[str, list],
) -> tuple[GraphSettings, dict[str, object], str, str, Any, Any]:
    config = load_source_config()
    graph_panel = st.sidebar.expander("Graph", expanded=True)
    mode_options = list(GRAPH_MODE_PRESETS)
    default_mode = "Citation graph"
    graph_mode = graph_panel.selectbox("Mode", mode_options, index=mode_options.index(default_mode))
    default_edge_types = GRAPH_MODE_PRESETS[graph_mode]
    edge_types = graph_panel.multiselect(
        "Edge types",
        options=EDGE_TYPES,
        default=default_edge_types,
        format_func=lambda value: EDGE_LABELS.get(value, value),
    )
    min_edge_weight = graph_panel.slider("Minimum edge weight", 0.0, 12.0, 0.0, 0.5)
    similarity_threshold = graph_panel.slider("Similarity threshold", 0.05, 0.95, 0.28, 0.01)
    color_mode = graph_panel.selectbox("Color by", ["cluster", "tag", "year", "collection"], index=3)
    export_panel = st.sidebar.container()

    graph_panel.markdown("**Search**")
    query = graph_panel.text_input("Search papers")

    graph_panel.markdown("**Filters**")
    tags = graph_panel.multiselect("Tags", facets["tags"])
    authors = graph_panel.multiselect("Authors", facets["authors"])
    saved_collections = _valid_saved_options(ensure_list(config.get("selected_collections")), facets["collections"])
    collections = graph_panel.multiselect("Collections", facets["collections"], default=saved_collections)
    if collections != saved_collections:
        _save_source_config_update({"selected_collections": collections})
    years = facets["years"]
    year_range: tuple[int, int] | None = None
    if len(years) > 1:
        selected_years = graph_panel.slider("Year range", min(years), max(years), (min(years), max(years)))
        year_range = (int(selected_years[0]), int(selected_years[1]))
    elif len(years) == 1:
        graph_panel.caption(f"Year: {years[0]}")

    settings = GraphSettings(
        included_edge_types=edge_types,
        min_edge_weight=float(min_edge_weight),
        similarity_threshold=float(similarity_threshold),
    )
    filters = {
        "query": query,
        "tags": tags,
        "authors": authors,
        "collections": collections,
        "year_range": year_range,
    }
    return settings, filters, color_mode, graph_mode, graph_panel, export_panel


def _papers_list(graph, selected_mode: str, source_fingerprint: str, theme: str) -> list[str]:
    st.markdown("**Papers**")
    with st.expander("Graph metrics", expanded=False):
        _graph_summary(graph, selected_mode, theme)

    rows = _paper_rows(graph)
    if not rows:
        st.write("No visible papers.")
        return []

    id_order = [row["Paper ID"] for row in rows]
    dataframe = pd.DataFrame(rows)

    table_event = st.dataframe(
        _dataframe_for_theme(dataframe, theme),
        use_container_width=True,
        hide_index=True,
        height=380,
        column_order=[
            "Citekey",
            "Title",
            "Year",
            "Authors",
            "Tags",
            "Collections",
            "Cluster",
            "Degree",
            "Read",
        ],
        on_select="rerun",
        selection_mode="multi-row",
        key=f"papers_table_{source_fingerprint[:12]}",
    )

    with st.expander("Cluster summary", expanded=False):
        st.dataframe(
            _dataframe_for_theme(pd.DataFrame(cluster_summary(graph)), theme),
            use_container_width=True,
            hide_index=True,
        )

    return _node_ids_from_table_event(table_event, id_order)


def _graph_summary(graph, selected_mode: str, theme: str) -> None:
    clusters = len({data.get("cluster", -1) for _, data in graph.nodes(data=True)}) if graph.number_of_nodes() else 0
    citation_edges = sum(1 for _, _, data in graph.edges(data=True) if "cites" in data.get("edge_types", []))
    reference_sources = sum(
        1 for _, data in graph.nodes(data=True) if getattr(data.get("paper"), "important_references", [])
    )
    summary = pd.DataFrame(
        [
            {"Metric": "Papers", "Value": graph.number_of_nodes()},
            {"Metric": "Edges", "Value": graph.number_of_edges()},
            {"Metric": "Citation edges", "Value": citation_edges},
            {"Metric": "Reference sources", "Value": reference_sources},
            {"Metric": "Clusters", "Value": clusters},
            {"Metric": "Mode", "Value": selected_mode},
        ]
    )
    st.dataframe(_dataframe_for_theme(summary, theme), use_container_width=True, hide_index=True, height=240)


def _paper_rows(graph) -> list[dict[str, Any]]:
    rows = []
    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        rows.append(
            {
                "Paper ID": node_id,
                "Citekey": paper.citekey,
                "Title": paper.title,
                "Authors": "; ".join(paper.authors),
                "Year": paper.year,
                "Tags": "; ".join(paper.tags),
                "Collections": "; ".join(paper.collections),
                "Cluster": data.get("cluster", -1),
                "Degree": round(float(graph.degree(node_id, weight="weight")), 2),
                "Read": paper.read_status,
            }
        )
    return rows


def _downloads(graph, graph_html: str, container: Any | None = None) -> None:
    target = container or st.sidebar
    with target.expander("Export", expanded=False):
        st.download_button("HTML", graph_html, "graph.html", "text/html", use_container_width=True)
        st.download_button("JSON", graph_to_json(graph), "graph.json", "application/json", use_container_width=True)
        st.download_button(
            "GraphML",
            graph_to_graphml_bytes(graph),
            "graph.graphml",
            "application/graphml+xml",
            use_container_width=True,
        )
        if st.button("Save files", use_container_width=True):
            write_export("graph.html", graph_html)
            write_export("graph.json", graph_to_json(graph))
            write_export("graph.graphml", graph_to_graphml_bytes(graph))
            st.toast("Saved to graphature_project/exports")


def _paper_detail(
    graph,
    selected_paper_id: str | None,
    selected_ids: list[str],
    facets: dict[str, list],
    theme: str,
) -> None:
    st.subheader("Selected Paper")
    if not selected_paper_id or selected_paper_id not in graph:
        st.write("Select a paper in the graph or papers list.")
        return

    paper = graph.nodes[selected_paper_id].get("paper")
    st.markdown(f"### {paper.title or paper.citekey}")
    st.caption(paper.citekey)
    if paper.authors:
        st.write(", ".join(paper.authors))
    if paper.year or paper.venue:
        st.write(" | ".join(part for part in [str(paper.year or ""), paper.venue] if part))
    if paper.doi:
        st.write(f"DOI: {paper.doi}")

    _single_paper_editor(paper, facets)
    if len(selected_ids) > 1:
        _bulk_property_editor(graph, selected_ids, facets)

    if paper.abstract:
        st.markdown("**Abstract**")
        st.write(paper.abstract)
    if paper.notes_content:
        st.markdown("**Notes**")
        st.write(paper.notes_content)

    st.markdown("**Connected Papers**")
    rows = edge_explanations_for_paper(graph, selected_paper_id)
    if rows:
        st.dataframe(_dataframe_for_theme(pd.DataFrame(rows), theme), use_container_width=True, hide_index=True)
    else:
        st.write("No visible connections under the current settings.")


def _dataframe_for_theme(dataframe: pd.DataFrame, theme: str):
    if theme != "dark":
        return dataframe
    return dataframe.style.set_properties(
        **{
            "background-color": "#0f172a",
            "color": "#e5e7eb",
            "border-color": "#334155",
        }
    ).set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", "#111827"),
                    ("color", "#e5e7eb"),
                    ("border-color", "#334155"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("background-color", "#0f172a"),
                    ("color", "#e5e7eb"),
                    ("border-color", "#334155"),
                ],
            },
        ]
    )


def _single_paper_editor(paper, facets: dict[str, list]) -> None:
    tag_options, tag_defaults = _multiselect_options_and_defaults(facets["tags"], paper.tags)
    collection_options, collection_defaults = _multiselect_options_and_defaults(
        facets["collections"],
        paper.collections,
    )
    with st.form(f"single_props_{paper.id}"):
        tags = st.multiselect(
            "Tags",
            tag_options,
            default=tag_defaults,
            accept_new_options=True,
        )
        collections = st.multiselect(
            "Collections",
            collection_options,
            default=collection_defaults,
            accept_new_options=True,
        )
        read_status = st.checkbox("Read", value=paper.read_status)
        submitted = st.form_submit_button("Save selected paper")

    if submitted:
        update_paper_overrides(
            [paper],
            {
                "tags": tags,
                "collections": collections,
                "read_status": read_status,
            },
        )
        st.rerun()


def _bulk_property_editor(graph, selected_ids: list[str], facets: dict[str, list]) -> None:
    selected_papers = [graph.nodes[node_id].get("paper") for node_id in selected_ids if node_id in graph]
    existing_tags = sorted({tag for paper in selected_papers for tag in paper.tags}, key=str.lower)
    with st.expander(f"Bulk Properties ({len(selected_papers)} papers)", expanded=True):
        with st.form("bulk_props"):
            add_tags = st.multiselect("Add tags", facets["tags"], accept_new_options=True)
            remove_tags = st.multiselect("Remove tags", existing_tags)
            add_collections = st.multiselect("Add collections", facets["collections"], accept_new_options=True)
            read_choice = st.selectbox("Read status", ["No change", "Read", "Unread"])
            submitted = st.form_submit_button("Apply to selected papers")

    if submitted:
        for paper in selected_papers:
            tags = [tag for tag in paper.tags if tag not in remove_tags]
            tags = unique_clean_strings([*tags, *add_tags])
            collections = unique_clean_strings([*paper.collections, *add_collections])
            read_status = None
            if read_choice == "Read":
                read_status = True
            elif read_choice == "Unread":
                read_status = False
            update_paper_overrides(
                [paper],
                {
                    "tags": tags,
                    "collections": collections,
                    "read_status": read_status,
                },
            )
        st.rerun()


def _multiselect_options_and_defaults(options: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    """Return Streamlit-safe multiselect options and defaults."""

    defaults = unique_clean_strings(ensure_list(current))
    choices = unique_clean_strings([*ensure_list(options), *defaults])
    option_by_key = {normalize_key(option): option for option in choices}
    resolved_defaults: list[str] = []
    for value in defaults:
        key = normalize_key(value)
        if key not in option_by_key:
            option_by_key[key] = value
            choices.append(value)
        resolved_defaults.append(option_by_key[key])
    return choices, unique_clean_strings(resolved_defaults)


def _valid_saved_options(saved: list[Any], options: list[str]) -> list[str]:
    option_by_key = {normalize_key(option): option for option in options}
    values = []
    for value in unique_clean_strings(saved):
        option = option_by_key.get(normalize_key(value))
        if option:
            values.append(option)
    return values


def _valid_selected_ids(graph) -> list[str]:
    return [node_id for node_id in st.session_state.selected_paper_ids if node_id in graph]


def _set_selected_ids(node_ids: list[str]) -> None:
    st.session_state.selected_paper_ids = unique_clean_strings(node_ids)


def _graph_key(graph, color_mode: str, graph_theme: str) -> str:
    payload = {
        "color_mode": color_mode,
        "graph_theme": graph_theme,
        "visual_version": GRAPH_VISUAL_VERSION,
        "nodes": [],
        "edges": [],
    }
    for node_id, data in sorted(graph.nodes(data=True), key=lambda item: str(item[0])):
        paper = data.get("paper")
        payload["nodes"].append(
            {
                "id": str(node_id),
                "label": getattr(paper, "label", ""),
                "title": getattr(paper, "title", ""),
                "tags": getattr(paper, "tags", []),
                "collections": getattr(paper, "collections", []),
                "year": getattr(paper, "year", None),
                "cluster": data.get("cluster", -1),
                "degree": float(graph.degree(node_id, weight="weight")),
            }
        )
    for source, target, data in sorted(graph.edges(data=True), key=lambda item: (str(item[0]), str(item[1]))):
        payload["edges"].append(
            {
                "source": str(source),
                "target": str(target),
                "weight": data.get("weight", 0.0),
                "reasons": data.get("reasons", []),
            }
        )
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _node_ids_from_graph_event(event, graph) -> list[str]:
    if not isinstance(event, dict):
        return _valid_selected_ids(graph)
    node_ids = event.get("selected_ids", [])
    if not isinstance(node_ids, list):
        return _valid_selected_ids(graph)
    return [node_id for node_id in unique_clean_strings(node_ids) if node_id in graph]


def _node_ids_from_table_event(event, id_order: list[str]) -> list[str]:
    try:
        rows = event.selection.rows
    except AttributeError:
        try:
            rows = event.get("selection", {}).get("rows", [])
        except AttributeError:
            rows = []
    node_ids: list[str] = []
    for row_index in rows or []:
        if isinstance(row_index, int) and 0 <= row_index < len(id_order):
            node_ids.append(id_order[row_index])
    return node_ids


def _inject_css(theme: str) -> None:
    dark = theme == "dark"
    colors = {
        "bg": "#0b1120" if dark else "#ffffff",
        "surface": "#111827" if dark else "#f8fbff",
        "panel": "#0f172a" if dark else "#ffffff",
        "field": "#111827" if dark else "#ffffff",
        "text": "#e5e7eb" if dark else "#0f172a",
        "muted": "#94a3b8" if dark else "#0f766e",
        "brand": "#7dd3fc" if dark else "#075985",
        "border": "#334155" if dark else "#dbeafe",
        "border_strong": "#38bdf8" if dark else "#7dd3fc",
        "accent": "#38bdf8" if dark else "#0284c7",
        "accent_strong": "#7dd3fc" if dark else "#075985",
        "accent_soft": "#102a43" if dark else "#e0f2fe",
        "accent_focus": "#164e63" if dark else "#dbeafe",
        "button_hover": "#164e63" if dark else "#bae6fd",
    }
    color_scheme = "dark" if dark else "light"
    primary_rgb = "56, 189, 248" if dark else "2, 132, 199"

    st.markdown(
        f"""
        <style>
        :root,
        html,
        body,
        .stApp,
        [data-testid="stAppViewContainer"] {{
            --primary-color: {colors["accent"]} !important;
            --primary-color-rgb: {primary_rgb} !important;
            --graphature-bg: {colors["bg"]};
            --graphature-surface: {colors["surface"]};
            --graphature-panel: {colors["panel"]};
            --graphature-field: {colors["field"]};
            --graphature-text: {colors["text"]};
            --graphature-muted: {colors["muted"]};
            --graphature-brand: {colors["brand"]};
            --graphature-border: {colors["border"]};
            --graphature-border-strong: {colors["border_strong"]};
            --graphature-accent: {colors["accent"]};
            --graphature-accent-strong: {colors["accent_strong"]};
            --graphature-accent-soft: {colors["accent_soft"]};
            --graphature-accent-focus: {colors["accent_focus"]};
            --graphature-button-hover: {colors["button_hover"]};
            color-scheme: {color_scheme};
        }}
        .block-container {{
            padding: 0.35rem 0.6rem 1rem;
            max-width: none;
            width: 100%;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            width: 100%;
        }}
        [data-testid="stMainBlockContainer"] {{
            max-width: none;
            padding-left: 0.6rem;
            padding-right: 0.6rem;
        }}
        [data-testid="stHorizontalBlock"] {{
            gap: 0.6rem;
        }}
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"],
        [data-testid="stToolbar"] {{
            background: var(--graphature-bg) !important;
            color: var(--graphature-text) !important;
            color-scheme: {color_scheme};
        }}
        [data-testid="stHeader"],
        [data-testid="stToolbar"] {{
            border-color: var(--graphature-border) !important;
        }}
        .stApp input,
        .stApp textarea,
        .stApp select {{
            accent-color: var(--graphature-accent) !important;
        }}
        [data-testid="stSidebar"] {{
            background: var(--graphature-surface) !important;
            border-right: 1px solid var(--graphature-border);
            color: var(--graphature-text) !important;
        }}
        [data-testid="stSidebar"][aria-expanded="true"] {{
            min-width: 21.5rem !important;
            width: 21.5rem !important;
            max-width: 21.5rem !important;
        }}
        [data-testid="stSidebar"][aria-expanded="false"] {{
            min-width: 0 !important;
            width: 0 !important;
            max-width: 0 !important;
            border-right: 0;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
            gap: 0.45rem;
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{
            padding: 0.25rem 0.75rem 1rem;
        }}
        .app-brand-row {{
            display: grid;
            grid-template-columns: 3.1rem minmax(0, 1fr);
            align-items: center;
            gap: 0.7rem;
            margin: 0 0 0.85rem;
        }}
        .app-brand-logo-wrap {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 3.1rem;
            height: 3.1rem;
            border: 1px solid var(--graphature-border);
            border-radius: 10px;
            background: #ffffff;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
        }}
        .app-brand-logo {{
            display: block;
            width: 2.35rem;
            height: 2.35rem;
            object-fit: contain;
        }}
        .app-brand-copy {{
            min-width: 0;
        }}
        .app-brand {{
            margin: 0 0 0.08rem;
            color: var(--graphature-brand);
            font-size: 1.85rem;
            font-weight: 760;
            letter-spacing: 0;
            line-height: 1.05;
        }}
        .app-brand-subtitle {{
            margin: 0;
            color: var(--graphature-muted);
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.01em;
        }}
        [data-testid="stCustomComponentV1"] {{
            display: block;
            background: var(--graphature-bg);
        }}
        iframe[title="app.graphature_vis_graph_v2"] {{
            display: block;
            width: 100% !important;
        }}
        [data-testid="stColumn"]:has(.detail-panel-anchor) {{
            position: sticky;
            top: 0.35rem;
            align-self: flex-start;
            height: calc(100vh - 0.7rem);
            overflow-y: auto;
            overscroll-behavior: contain;
            padding-right: 0.2rem;
        }}
        [data-testid="stDataFrame"] {{
            width: 100%;
            overflow: hidden;
            border: 1px solid var(--graphature-border);
            border-radius: 8px;
            background: var(--graphature-panel) !important;
            color-scheme: {color_scheme};
        }}
        [data-testid="stDataFrame"] canvas,
        [data-testid="stDataFrame"] [role="grid"],
        [data-testid="stDataFrame"] [role="row"],
        [data-testid="stDataFrame"] [role="columnheader"],
        [data-testid="stDataFrame"] [role="gridcell"] {{
            background-color: var(--graphature-panel) !important;
            color: var(--graphature-text) !important;
        }}
        [data-testid="stExpander"],
        [data-testid="stVerticalBlockBorderWrapper"] {{
            width: 100%;
        }}
        [data-testid="stExpander"] details {{
            background: var(--graphature-panel) !important;
            border-color: var(--graphature-border) !important;
            color: var(--graphature-text) !important;
        }}
        [data-baseweb="tag"] {{
            background-color: var(--graphature-accent-soft) !important;
            border: 1px solid var(--graphature-border-strong) !important;
            color: var(--graphature-accent-strong) !important;
        }}
        [data-baseweb="tag"] span {{
            color: var(--graphature-accent-strong) !important;
        }}
        [data-baseweb="tag"] svg {{
            color: var(--graphature-accent) !important;
        }}
        [data-baseweb="menu"] {{
            background: var(--graphature-panel) !important;
            color: var(--graphature-text) !important;
        }}
        [data-baseweb="menu"] [aria-selected="true"],
        [role="option"][aria-selected="true"] {{
            background-color: var(--graphature-accent-soft) !important;
            color: var(--graphature-accent-strong) !important;
        }}
        [data-baseweb="menu"] [aria-selected="true"] svg,
        [role="option"][aria-selected="true"] svg {{
            color: var(--graphature-accent) !important;
            fill: var(--graphature-accent) !important;
        }}
        [data-baseweb="checkbox"]:has(input:checked) > span:first-child {{
            background-color: var(--graphature-accent) !important;
            border-color: var(--graphature-accent) !important;
        }}
        [data-testid="stCheckbox"] input,
        [data-baseweb="checkbox"] input {{
            accent-color: var(--graphature-accent) !important;
        }}
        [data-testid="stCheckbox"] label:has(input:checked) > span:first-child,
        [data-baseweb="checkbox"] input:checked ~ span,
        [data-baseweb="checkbox"] span:has(+ input:checked) {{
            background-color: var(--graphature-accent) !important;
            border-color: var(--graphature-accent) !important;
        }}
        [data-baseweb="checkbox"]:has(input:focus) > span:first-child {{
            box-shadow: 0 0 0 3px var(--graphature-accent-focus) !important;
        }}
        [data-baseweb="checkbox"] > span:first-child {{
            border-color: var(--graphature-border-strong) !important;
        }}
        [data-baseweb="slider"] [role="slider"] {{
            background-color: var(--graphature-accent) !important;
            border-color: var(--graphature-accent-strong) !important;
            box-shadow: 0 0 0 3px var(--graphature-accent-focus) !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] *,
        [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"],
        [data-testid="stSlider"] [data-baseweb="slider"] [aria-valuenow],
        [data-testid="stSlider"] [data-baseweb="slider"] [aria-valuetext] {{
            color: var(--graphature-accent-strong) !important;
            border-color: var(--graphature-accent) !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] div[style*="rgb(255, 75, 75)"],
        [data-testid="stSlider"] [data-baseweb="slider"] div[style*="#ff4b4b"],
        [data-testid="stSlider"] [data-baseweb="slider"] span[style*="rgb(255, 75, 75)"],
        [data-testid="stSlider"] [data-baseweb="slider"] span[style*="#ff4b4b"] {{
            color: var(--graphature-accent-strong) !important;
            background-color: var(--graphature-accent) !important;
            border-color: var(--graphature-accent) !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] div[style*="background-color: rgb(255, 75, 75)"],
        [data-testid="stSlider"] [data-baseweb="slider"] div[style*="background: rgb(255, 75, 75)"] {{
            background-color: var(--graphature-accent) !important;
            background: var(--graphature-accent) !important;
        }}
        [data-baseweb="slider"] [role="slider"]:focus {{
            box-shadow: 0 0 0 4px var(--graphature-accent-focus) !important;
        }}
        [data-baseweb="slider"] div[style*="height: 0.25rem"] {{
            background: var(--graphature-border-strong) !important;
        }}
        [data-baseweb="select"] > div,
        [data-testid="stTextInput"] input,
        [data-testid="stFileUploader"] section,
        [data-testid="stTextArea"] textarea {{
            background-color: var(--graphature-field) !important;
            border-color: var(--graphature-border-strong) !important;
            color: var(--graphature-text) !important;
        }}
        [data-baseweb="select"]:focus-within > div,
        [data-testid="stTextInput"] input:focus,
        [data-testid="stFileUploader"] section:focus-within,
        [data-testid="stTextArea"] textarea:focus {{
            border-color: var(--graphature-accent) !important;
            box-shadow: 0 0 0 3px var(--graphature-accent-focus) !important;
        }}
        .stDownloadButton button,
        .stButton button,
        [data-testid="stFormSubmitButton"] button {{
            border-radius: 6px;
            background: var(--graphature-accent-soft) !important;
            border: 1px solid var(--graphature-border-strong) !important;
            color: var(--graphature-accent-strong) !important;
        }}
        .stDownloadButton button:hover,
        .stButton button:hover,
        [data-testid="stFormSubmitButton"] button:hover {{
            background: var(--graphature-button-hover) !important;
            border-color: var(--graphature-accent) !important;
            color: var(--graphature-accent-strong) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
