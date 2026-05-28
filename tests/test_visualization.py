import networkx as nx

from graphature.models import Paper
from graphature.visualization import graph_to_vis_data


def test_graph_to_vis_data_marks_read_papers():
    graph = nx.Graph()
    graph.add_node("read-paper", paper=Paper(id="read-paper", citekey="read", read_status=True))
    graph.add_node("unread-paper", paper=Paper(id="unread-paper", citekey="unread", read_status=False))

    payload = graph_to_vis_data(graph)
    by_id = {node["id"]: node for node in payload["nodes"]}

    assert by_id["read-paper"]["read_status"] is True
    assert by_id["unread-paper"]["read_status"] is False
