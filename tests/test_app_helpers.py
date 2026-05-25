from pathlib import Path

from app import _clean_local_path_text, _local_path_from_input


def test_clean_local_path_text_accepts_quoted_and_file_uri_paths():
    assert _clean_local_path_text(' "C:/tmp/zotero.sqlite" ') == "C:/tmp/zotero.sqlite"
    assert _clean_local_path_text("file:///C:/tmp/zotero.sqlite") == "C:/tmp/zotero.sqlite"


def test_zotero_path_input_accepts_database_directory(tmp_path):
    database = tmp_path / "zotero.sqlite"
    database.write_text("", encoding="utf-8")

    assert _local_path_from_input(str(tmp_path), default_filename="zotero.sqlite") == database
    assert _local_path_from_input(str(database), default_filename="zotero.sqlite") == database
