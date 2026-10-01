"""Tests for the draft Merritt manifest CSV export."""
import csv
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.merritt_manifest import (  # noqa: E402
    MANIFEST_FIELDS,
    build_manifest_csv,
    suggest_manifest_mapping,
)


def test_headers_are_exact_and_ordered():
    headers = [h for _, _, h in MANIFEST_FIELDS]
    assert headers == [
        "nfo:fileName",
        "mrt:localIdentifier",
        "mrt:creator",
        "mrt:title",
        "mrt:date",
    ]


def test_suggest_mapping_on_abbott_like_columns():
    cols = ["Filename", "Primary File Name", "Creator", "Title",
            "Collection Title", "Date Created Index"]
    s = suggest_manifest_mapping(cols)
    # filename (with extension) preferred for the file; bare "Filename" -> local id
    assert s["filename"] == "Primary File Name"
    assert s["local_identifier"] == "Filename"
    assert s["creator"] == "Creator"
    assert s["title"] == "Title"             # exact wins over "Collection Title"
    assert s["date"] == "Date Created Index"


def _frame():
    return pd.DataFrame(
        {
            "Primary File Name": ["a.tif", "b.tif", ""],
            "Filename": ["a", "b", "c"],
            "Creator": ["Abbott, Chuck|Abbott, Esther", "Jones, Pat", ""],
            "Title": ["First", "Second", "Third"],
            "Date Created Index": ["1970", "1971", ""],
        },
        dtype="string",
    )


def _mapping():
    return {
        "filename": "Primary File Name",
        "local_identifier": "Filename",
        "creator": "Creator",
        "title": "Title",
        "date": "Date Created Index",
    }


def test_build_manifest_first_value_only():
    data, summary = build_manifest_csv(_frame(), _mapping())
    text = data.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["nfo:fileName", "mrt:localIdentifier", "mrt:creator", "mrt:title", "mrt:date"]
    # first object: multi-value creator reduced to the first value only
    assert rows[1] == ["a.tif", "a", "Abbott, Chuck", "First", "1970"]
    assert summary["row_count"] == 3


def test_build_manifest_is_utf8():
    df = pd.DataFrame(
        {"Filename": ["x"], "Title": ["Café façade — señor"]}, dtype="string"
    )
    data, _ = build_manifest_csv(df, {"local_identifier": "Filename", "title": "Title"})
    # round-trips cleanly as UTF-8
    assert "Café façade — señor" in data.decode("utf-8")


def test_build_manifest_requires_a_mapping():
    try:
        build_manifest_csv(_frame(), {k: "" for k, _, _ in MANIFEST_FIELDS})
    except ValueError as e:
        assert "mapped" in str(e)
    else:
        raise AssertionError("expected ValueError when nothing is mapped")


def test_unmapped_fields_are_blank_columns():
    # only map title; other columns should be present but empty
    data, _ = build_manifest_csv(_frame(), {"title": "Title"})
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert rows[1] == ["", "", "", "First", ""]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All Merritt manifest tests passed.")
