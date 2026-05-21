from pathlib import Path

from papergraph.clustering import assign_communities
from papergraph.graph_builder import GraphSettings, build_graph, edge_explanations_for_paper
from papergraph.importers import merge_manual_metadata, parse_bibtex_text, parse_manual_metadata_text


ROOT = Path(__file__).resolve().parents[1]


def _sample_papers():
    papers = parse_bibtex_text((ROOT / "examples" / "sample_library.bib").read_text(encoding="utf-8"))
    manual = parse_manual_metadata_text((ROOT / "examples" / "sample_manual_metadata.yaml").read_text(encoding="utf-8"))
    return merge_manual_metadata(papers, manual)


def test_graph_contains_explainable_weighted_edges():
    graph = build_graph(_sample_papers(), GraphSettings(similarity_threshold=0.15))

    assert graph.number_of_nodes() == 8
    assert graph.number_of_edges() > 0

    muller_id = next(node for node, data in graph.nodes(data=True) if data["paper"].citekey == "muller2007pbd")
    macklin_id = next(node for node, data in graph.nodes(data=True) if data["paper"].citekey == "macklin2016xpbd")

    assert graph.has_edge(muller_id, macklin_id)
    edge = graph.edges[muller_id, macklin_id]
    assert edge["weight"] >= 5.0
    assert "manual_related" in edge["edge_types"]
    assert edge["reasons"]


def test_edge_explanations_and_clusters_are_available():
    graph = assign_communities(build_graph(_sample_papers(), GraphSettings(similarity_threshold=0.15)))
    muller_id = next(node for node, data in graph.nodes(data=True) if data["paper"].citekey == "muller2007pbd")

    rows = edge_explanations_for_paper(graph, muller_id)

    assert rows
    assert "Reasons" in rows[0]
    assert all("cluster" in data for _, data in graph.nodes(data=True))


def test_citation_edges_are_auto_detected_from_reference_text():
    papers = parse_bibtex_text(
        """
        @article{source2020,
          title = {A Later Simulation Paper},
          author = {Doe, Jane},
          year = {2020},
          references = {[@muller2007pbd]
            Macklin, Miles and Muller, Matthias. XPBD: Position-Based Simulation of Compliant Constrained Dynamics. Motion in Games, 2016.
            doi:10.5555/contact.2018
            Baraff et al. 1996}
        }

        @article{muller2007pbd,
          title = {Position Based Dynamics},
          author = {Muller, Matthias},
          year = {2007}
        }

        @inproceedings{macklin2016xpbd,
          title = {XPBD: Position-Based Simulation of Compliant Constrained Dynamics},
          author = {Macklin, Miles and Muller, Matthias},
          year = {2016}
        }

        @article{contact2018,
          title = {A Very Specific Method for Contact Mechanics},
          author = {Smith, Alex},
          year = {2018},
          doi = {10.5555/contact.2018}
        }

        @inproceedings{baraff1996linear,
          title = {Linear-Time Dynamics Using Lagrange Multipliers},
          author = {Baraff, David},
          year = {1996}
        }
        """
    )
    graph = build_graph(papers, GraphSettings(included_edge_types=["cites"]))
    by_key = {data["paper"].citekey: node for node, data in graph.nodes(data=True)}

    for target in ["muller2007pbd", "macklin2016xpbd", "contact2018", "baraff1996linear"]:
        assert graph.has_edge(by_key["source2020"], by_key[target])
        edge = graph.edges[by_key["source2020"], by_key[target]]
        assert edge["edge_types"] == ["cites"]
        assert "cites/references" in "; ".join(edge["reasons"])

    evidence = graph.edges[by_key["source2020"], by_key["contact2018"]]["evidence"]["cites"][0]
    assert evidence["match_type"] == "doi"
