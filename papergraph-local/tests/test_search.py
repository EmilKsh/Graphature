from papergraph.models import Paper
from papergraph.search import available_facets, filter_papers


def test_collection_filter_includes_nested_collection_paths():
    papers = [
        Paper(id="p1", citekey="a", collections=["Simulation Intelligence / Fundamentals"]),
        Paper(id="p2", citekey="b", collections=["Simulation Intelligence / Discrete Mechanics"]),
        Paper(id="p3", citekey="c", collections=["Other"]),
    ]

    filtered = filter_papers(papers, collections=["Simulation Intelligence"])

    assert [paper.citekey for paper in filtered] == ["a", "b"]


def test_available_facets_include_collection_ancestors():
    papers = [Paper(id="p1", citekey="a", collections=["Simulation Intelligence / Fundamentals"])]

    facets = available_facets(papers)

    assert "Simulation Intelligence" in facets["collections"]
    assert "Simulation Intelligence / Fundamentals" in facets["collections"]
