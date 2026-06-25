"""Tests for merging a new spreadsheet into a master spreadsheet."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.sheet_merge import merge_sheets  # noqa: E402


def _master() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["1", "2", "3"],
            "name": ["Alice", "Bob", "Carol"],
            "notes": [pd.NA, "short", "Detailed note here"],  # row2 blank
        },
        dtype="string",
    )


def _new() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["1", "2", "4"],          # 4 is brand new
            "name": ["Alice", "Bob", "Dave"],
            "notes": ["Filled in!", "a much longer, more detailed note", "new row note"],
            "email": ["a@x.com", "b@x.com", "d@x.com"],  # brand-new column
        },
        dtype="string",
    )


def test_fills_blank_master_cell():
    r = merge_sheets(_master(), _new(), ["id"])
    # 3 blanks filled: notes for id=1, plus the new `email` column for id=1 & id=2
    assert r.cells_filled == 3
    filled = [c for c in r.changes if c.reason == "filled_blank"]
    notes_fill = [c for c in filled if c.column == "notes"]
    assert notes_fill and notes_fill[0].new_value == "Filled in!"


def test_longer_value_wins():
    r = merge_sheets(_master(), _new(), ["id"])
    # id=2 notes "short" -> longer new note
    assert r.cells_updated == 1
    upd = [c for c in r.changes if c.reason == "longer_wins"][0]
    assert upd.old_value == "short"


def test_new_rows_appended():
    r = merge_sheets(_master(), _new(), ["id"])
    assert r.rows_added == 1  # id=4
    assert r.merged_row_count == 4


def test_new_columns_added():
    r = merge_sheets(_master(), _new(), ["id"])
    assert r.columns_added == ["email"]


def test_shorter_new_value_is_kept_difference_not_applied():
    master = pd.DataFrame(
        {"id": ["1"], "title": ["A nice long title"]}, dtype="string"
    )
    new = pd.DataFrame({"id": ["1"], "title": ["Short"]}, dtype="string")
    r = merge_sheets(master, new, ["id"])
    assert r.cells_updated == 0
    assert r.differences_kept == 1
    assert r.kept_differences[0].master_value == "A nice long title"


def test_master_never_mutated():
    master = _master()
    before = master.copy()
    merge_sheets(master, _new(), ["id"])
    assert master.equals(before)  # original frame untouched


def test_report_and_csv_produced():
    r = merge_sheets(_master(), _new(), ["id"])
    assert r.merged_csv.startswith(b"id,name,notes,email")
    assert "# Spreadsheet merge report" in r.report_markdown


def test_missing_key_raises():
    try:
        merge_sheets(_master(), _new(), ["nonexistent"])
    except ValueError as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("expected ValueError for missing key column")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All merge tests passed.")
