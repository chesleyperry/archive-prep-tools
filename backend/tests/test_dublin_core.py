"""Tests for the Dublin Core XML export."""
import io
import os
import sys
import zipfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.dublin_core import (  # noqa: E402
    build_dc_zip,
    row_to_dc_xml,
    sanitize_filename,
    suggest_mapping,
)


def test_suggest_mapping_matches_common_columns():
    cols = ["Title", "Creator", "Topics", "Place", "Date Created Index",
            "Physical Description", "Description", "Accession Number"]
    s = suggest_mapping(cols)
    assert s["Title"] == "title"
    assert s["Creator"] == "creator"
    assert s["Topics"] == "subject"
    assert s["Place"] == "coverage"
    assert s["Date Created Index"] == "date"
    # longest-hint-wins: "physical description" -> format, not description
    assert s["Physical Description"] == "format"
    assert s["Description"] == "description"
    assert s["Accession Number"] == "identifier"


def test_suggest_mapping_unknown_is_none():
    assert suggest_mapping(["Primary File Name"])["Primary File Name"] is None


def test_row_to_xml_splits_multivalue_and_escapes():
    row = {"Creator": "Abbott, Chuck|Abbott, Esther", "Title": "A & B <ok>"}
    mapping = {"Creator": "creator", "Title": "title"}
    xml = row_to_dc_xml(row, mapping, split=True, delimiter="|")
    assert xml.count("<dc:creator>") == 2          # split into two
    assert "<dc:creator>Abbott, Chuck</dc:creator>" in xml
    assert "A &amp; B &lt;ok&gt;" in xml            # escaped
    # canonical order: title before creator
    assert xml.index("<dc:title>") < xml.index("<dc:creator>")


def test_row_to_xml_skips_empty_and_unmapped():
    row = {"Title": "T", "Note": "", "Junk": "x"}
    mapping = {"Title": "title", "Note": "description", "Junk": ""}
    xml = row_to_dc_xml(row, mapping)
    assert "<dc:title>T</dc:title>" in xml
    assert "<dc:description>" not in xml   # empty cell -> no tag
    assert ">x<" not in xml                # unmapped column -> ignored


def test_sanitize_filename():
    assert sanitize_filename("ms0039_s85_01") == "ms0039_s85_01"
    assert sanitize_filename("a/b:c*?") == "a_b_c"
    assert sanitize_filename("  ") == ""


def _frame():
    return pd.DataFrame(
        {
            "Filename": ["img_1", "img_2", "img_2", ""],  # dup + blank
            "Title": ["First", "Second", "Third", "Fourth"],
            "Creator": ["A|B", "C", "", "D"],
        },
        dtype="string",
    )


def test_build_zip_one_file_per_row_with_dedup_and_blank():
    mapping = {"Title": "title", "Creator": "creator", "Filename": ""}
    zbytes, summary = build_dc_zip(_frame(), mapping, "Filename")
    zf = zipfile.ZipFile(io.BytesIO(zbytes))
    names = sorted(zf.namelist())
    assert len(names) == 4
    assert "img_1.xml" in names
    assert "img_2.xml" in names and "img_2-1.xml" in names  # collision renamed
    assert any(n.startswith("row-4") for n in names)        # blank -> row-N
    assert summary.file_count == 4
    assert summary.blank_filenames == 1
    assert summary.renamed_collisions == 1
    # first file splits creator A|B into two elements
    assert zf.read("img_1.xml").decode().count("<dc:creator>") == 2


def test_build_zip_requires_a_mapping():
    try:
        build_dc_zip(_frame(), {"Title": "", "Creator": ""}, "Filename")
    except ValueError as e:
        assert "mapped" in str(e)
    else:
        raise AssertionError("expected ValueError when nothing is mapped")


def test_build_zip_bad_filename_column():
    try:
        build_dc_zip(_frame(), {"Title": "title"}, "NoSuchColumn")
    except ValueError as e:
        assert "not in the sheet" in str(e)
    else:
        raise AssertionError("expected ValueError for bad filename column")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All Dublin Core tests passed.")
