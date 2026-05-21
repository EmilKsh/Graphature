"""Graph visualization helpers for Graphature."""

from __future__ import annotations

import html
import json
from collections.abc import Hashable
from typing import Any

import networkx as nx
from pyvis.network import Network


PALETTE = [
    "#3b82f6",
    "#14b8a6",
    "#22c55e",
    "#8b5cf6",
    "#f59e0b",
    "#ec4899",
    "#06b6d4",
    "#84cc16",
    "#f97316",
    "#6366f1",
]

LIGHT_NODE_PALETTE = [
    "#60a5fa",
    "#2dd4bf",
    "#4ade80",
    "#a78bfa",
    "#fbbf24",
    "#f472b6",
    "#22d3ee",
    "#a3e635",
    "#fb923c",
    "#818cf8",
]

DARK_NODE_PALETTE = [
    "#93c5fd",
    "#5eead4",
    "#86efac",
    "#c4b5fd",
    "#fcd34d",
    "#f9a8d4",
    "#67e8f9",
    "#bef264",
    "#fdba74",
    "#a5b4fc",
]


def graph_to_vis_data(
    graph: nx.Graph,
    color_mode: str = "cluster",
    selected_paper_ids: list[str] | None = None,
    graph_theme: str = "light",
) -> dict[str, list[dict[str, Any]]]:
    """Return vis-network nodes and edges for the Streamlit component."""

    dark = graph_theme == "dark"
    color_lookup = _color_lookup(graph, color_mode, light_nodes=dark)

    nodes: list[dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        degree = graph.degree(node_id, weight="weight")
        size = min(34.0, 13.0 + float(degree) * 1.45)
        color = color_lookup.get(node_id, "#e5e7eb" if dark else "#7a8793")
        border_color = "#f8fafc" if dark else "#60a5fa"
        nodes.append(
            {
                "id": str(node_id),
                "label": getattr(paper, "label", data.get("label", str(node_id))),
                "title": _paper_tooltip(paper, data),
                "value": max(1.0, float(degree)),
                "size": size,
                "color": {
                    "background": color,
                    "border": border_color,
                    "highlight": {"background": color, "border": "#0284c7" if not dark else "#93c5fd"},
                },
                "borderWidth": 1.4,
                "font": {"color": "#f8fafc" if dark else "#1f2933"},
            }
        )

    edges: list[dict[str, Any]] = []
    for source, target, data in graph.edges(data=True):
        weight = float(data.get("weight", 1.0))
        edges.append(
            {
                "from": str(source),
                "to": str(target),
                "value": max(1.0, weight),
                "width": min(8.0, 1.0 + weight / 2.0),
                "title": html.escape("; ".join(data.get("reasons", []))),
            }
        )

    return {"nodes": nodes, "edges": edges}


def generate_pyvis_html(
    graph: nx.Graph,
    color_mode: str = "cluster",
    height: str = "720px",
    selected_paper_id: str | None = None,
) -> str:
    """Generate an interactive PyVis HTML graph."""

    net = Network(height=height, width="100%", bgcolor="#ffffff", font_color="#1f2933", cdn_resources="in_line")
    net.barnes_hut(gravity=-4200, central_gravity=0.22, spring_length=140, spring_strength=0.045, damping=0.12)

    color_lookup = _color_lookup(graph, color_mode)

    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        label = getattr(paper, "label", data.get("label", str(node_id)))
        degree = graph.degree(node_id, weight="weight")
        size = min(34, 12 + float(degree) * 1.4)
        border_width = 4 if node_id == selected_paper_id else 1
        net.add_node(
            node_id,
            label=label,
            title=_paper_tooltip(paper, data),
            color={"background": color_lookup.get(node_id, "#7a8793"), "border": "#1f2933"},
            size=size,
            borderWidth=border_width,
            shape="dot",
        )

    for source, target, data in graph.edges(data=True):
        weight = float(data.get("weight", 1.0))
        net.add_edge(
            source,
            target,
            value=max(1.0, weight),
            width=min(8.0, 1.0 + weight / 2.0),
            title=html.escape("; ".join(data.get("reasons", []))),
            color="#98a2b3",
        )

    net.set_options(
        json.dumps(
            {
                "interaction": {
                    "hover": True,
                    "tooltipDelay": 120,
                    "navigationButtons": False,
                    "keyboard": False,
                },
                "nodes": {
                    "font": {"size": 15, "face": "Inter, Segoe UI, Arial"},
                    "scaling": {"min": 12, "max": 34},
                },
                "edges": {
                    "smooth": {"type": "dynamic"},
                    "font": {"size": 0},
                    "color": {"inherit": False},
                },
                "physics": {
                    "stabilization": {"iterations": 220, "fit": True},
                    "minVelocity": 0.75,
                },
            }
        )
    )
    return net.generate_html(notebook=False)


def _paper_tooltip(paper: object, data: dict[str, object]) -> str:
    if paper is None:
        return html.escape(str(data.get("label", "")))

    authors = ", ".join(getattr(paper, "authors", []))
    tags = ", ".join(getattr(paper, "tags", []))
    collections = ", ".join(getattr(paper, "collections", []))
    parts = [
        f"<b>{html.escape(getattr(paper, 'title', '') or getattr(paper, 'citekey', ''))}</b>",
        html.escape(authors),
        html.escape(str(getattr(paper, "year", "") or "")),
        f"Tags: {html.escape(tags)}" if tags else "",
        f"Collections: {html.escape(collections)}" if collections else "",
    ]
    return "<br>".join(part for part in parts if part)


def _color_lookup(graph: nx.Graph, color_mode: str, light_nodes: bool = False) -> dict[Hashable, str]:
    values: dict[Hashable, object] = {}
    for node_id, data in graph.nodes(data=True):
        paper = data.get("paper")
        if color_mode == "tag":
            value = (getattr(paper, "tags", []) or ["untagged"])[0]
        elif color_mode == "year":
            year = getattr(paper, "year", None)
            value = f"{int(year) // 10 * 10}s" if year else "unknown"
        elif color_mode == "collection":
            value = (getattr(paper, "collections", []) or ["uncollected"])[0]
        else:
            value = data.get("cluster", -1)
        values[node_id] = value

    unique_values = {value: index for index, value in enumerate(sorted(set(values.values()), key=str))}
    palette = DARK_NODE_PALETTE if light_nodes else PALETTE
    return {node_id: palette[unique_values[value] % len(palette)] for node_id, value in values.items()}
