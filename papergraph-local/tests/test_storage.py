from papergraph.models import Paper
from papergraph.storage import apply_paper_overrides, load_paper_overrides, update_paper_overrides


def test_paper_overrides_round_trip(tmp_path):
    path = tmp_path / "paper_overrides.json"
    paper = Paper(id="paper-1", citekey="muller2007pbd", tags=["PBD"])

    update_paper_overrides(
        [paper],
        {"tags": ["XPBD", "constraints"], "collections": ["thesis"], "read_status": False},
        path=path,
    )

    overrides = load_paper_overrides(path)
    imported = [Paper(id="paper-1", citekey="muller2007pbd", tags=["old"])]
    apply_paper_overrides(imported, overrides)

    assert imported[0].tags == ["XPBD", "constraints"]
    assert imported[0].collections == ["thesis"]
    assert imported[0].read_status is False


def test_scalar_override_values_are_not_split_into_characters():
    imported = [Paper(id="paper-1", citekey="muller2007pbd", tags=["old"])]
    apply_paper_overrides(imported, {"muller2007pbd": {"tags": "Terramechanics"}})

    assert imported[0].tags == ["Terramechanics"]
