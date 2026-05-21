from papergraph.models import Paper
from papergraph.reference_extraction import _pdf_paths_from_paper


def test_pdf_paths_from_better_bibtex_file_field_unescapes_windows_paths():
    paper = Paper(
        id="p1",
        citekey="example2024",
        file_path=r"PDF:C\:\\Storage\\ZoteroLibrary\\Data\\storage\\ABCD1234\\Example Paper.pdf:application/pdf",
    )

    paths = _pdf_paths_from_paper(paper)

    assert len(paths) == 1
    assert str(paths[0]).replace("\\", "/").endswith(
        "C:/Storage/ZoteroLibrary/Data/storage/ABCD1234/Example Paper.pdf"
    )
