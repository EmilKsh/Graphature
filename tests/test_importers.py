from pathlib import Path
import sqlite3

from graphature.importers import merge_manual_metadata, parse_bibtex_text, parse_manual_metadata_text, parse_zotero_sqlite


ROOT = Path(__file__).resolve().parents[1]


def test_parse_bibtex_sample_maps_core_fields():
    papers = parse_bibtex_text((ROOT / "examples" / "sample_library.bib").read_text(encoding="utf-8"))

    by_key = {paper.citekey: paper for paper in papers}

    assert "muller2007pbd" in by_key
    assert by_key["muller2007pbd"].title == "Position Based Dynamics"
    assert by_key["muller2007pbd"].year == 2007
    assert "PBD" in by_key["muller2007pbd"].tags
    assert "constraint solvers" in by_key["muller2007pbd"].collections


def test_manual_metadata_merges_by_citekey():
    papers = parse_bibtex_text((ROOT / "examples" / "sample_library.bib").read_text(encoding="utf-8"))
    manual = parse_manual_metadata_text((ROOT / "examples" / "sample_manual_metadata.yaml").read_text(encoding="utf-8"))

    merged = merge_manual_metadata(papers, manual)
    by_key = {paper.citekey: paper for paper in merged}

    assert "XPBD" in by_key["macklin2016xpbd"].topic_labels
    assert "muller2007pbd" in by_key["macklin2016xpbd"].manual_related
    assert by_key["muller2007pbd"].notes_content.startswith("Important because")


def test_reference_fields_preserve_full_citations_with_commas():
    papers = parse_bibtex_text(
        """
        @article{source2020,
          title = {A Later Simulation Paper},
          author = {Doe, Jane},
          year = {2020},
          references = {Macklin, Miles and Muller, Matthias. XPBD: Position-Based Simulation of Compliant Constrained Dynamics. Motion in Games, 2016}
        }
        """
    )

    assert len(papers[0].important_references) == 1
    assert papers[0].important_references[0].startswith("Macklin, Miles")
    assert "Position-Based Simulation" in papers[0].important_references[0]


def test_note_fields_are_not_treated_as_citation_references():
    papers = parse_bibtex_text(
        """
        @article{source2020,
          title = {A Later Simulation Paper},
          author = {Doe, Jane},
          year = {2020},
          note = {arXiv:2011.00459 [cs]},
          annote = {Must read later}
        }
        """
    )

    assert papers[0].important_references == []


def test_parse_zotero_sqlite_reads_core_metadata(tmp_path):
    db_path = tmp_path / "zotero.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT);
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INTEGER);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER);
            CREATE TABLE collections (
                collectionID INTEGER PRIMARY KEY,
                collectionName TEXT,
                parentCollectionID INTEGER
            );
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, path TEXT);

            INSERT INTO itemTypes VALUES (1, 'journalArticle'), (2, 'attachment');
            INSERT INTO items VALUES (10, 1, 'ABCD1234'), (11, 2, 'ATTACH01');
            INSERT INTO fields VALUES (1, 'title'), (2, 'date'), (3, 'DOI'), (4, 'abstractNote'), (5, 'extra');
            INSERT INTO itemDataValues VALUES
                (1, 'A Zotero Paper'),
                (2, '2022-01-01'),
                (3, '10.1000/example'),
                (4, 'An abstract.'),
                (5, 'Citation Key: zotero2022paper');
            INSERT INTO itemData VALUES (10, 1, 1), (10, 2, 2), (10, 3, 3), (10, 4, 4), (10, 5, 5);
            INSERT INTO creators VALUES (1, 'Ada', 'Lovelace', 0);
            INSERT INTO itemCreators VALUES (10, 1, 0);
            INSERT INTO tags VALUES (1, 'simulation');
            INSERT INTO itemTags VALUES (10, 1);
            INSERT INTO collections VALUES (1, 'Simulation Intelligence', NULL);
            INSERT INTO collections VALUES (2, 'Fundamentals', 1);
            INSERT INTO collectionItems VALUES (2, 10);
            INSERT INTO itemAttachments VALUES (11, 10, 'storage:paper.pdf');
            """
        )

    papers = parse_zotero_sqlite(db_path)

    assert len(papers) == 1
    assert papers[0].citekey == "zotero2022paper"
    assert papers[0].title == "A Zotero Paper"
    assert papers[0].authors == ["Lovelace, Ada"]
    assert papers[0].year == 2022
    assert "simulation" in papers[0].tags
    assert papers[0].collections == ["Simulation Intelligence / Fundamentals"]
    assert papers[0].file_path.replace("\\", "/").endswith("storage/ATTACH01/paper.pdf")
