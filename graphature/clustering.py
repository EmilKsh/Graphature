"""Community detection helpers."""

from __future__ import annotations

import networkx as nx


def assign_communities(graph: nx.Graph) -> nx.Graph:
    """Assign a cluster id to every node using greedy modularity communities."""

    if graph.number_of_nodes() == 0:
        return graph

    if graph.number_of_edges() == 0:
        for cluster_id, node_id in enumerate(sorted(graph.nodes)):
            graph.nodes[node_id]["cluster"] = cluster_id
        return graph

    communities = nx.community.greedy_modularity_communities(graph, weight="weight")
    for cluster_id, community in enumerate(communities):
        for node_id in community:
            graph.nodes[node_id]["cluster"] = cluster_id
    return graph


def cluster_summary(graph: nx.Graph) -> list[dict[str, object]]:
    """Return a compact summary of detected clusters."""

    clusters: dict[int, list[str]] = {}
    for node_id, data in graph.nodes(data=True):
        clusters.setdefault(int(data.get("cluster", -1)), []).append(node_id)

    rows: list[dict[str, object]] = []
    for cluster_id, node_ids in sorted(clusters.items()):
        papers = [graph.nodes[node_id].get("paper") for node_id in node_ids]
        tags: dict[str, int] = {}
        for paper in papers:
            for tag in getattr(paper, "tags", []):
                tags[tag] = tags.get(tag, 0) + 1
        top_tags = ", ".join(tag for tag, _ in sorted(tags.items(), key=lambda item: item[1], reverse=True)[:5])
        rows.append({"Cluster": cluster_id, "Papers": len(node_ids), "Top tags": top_tags})
    return rows
