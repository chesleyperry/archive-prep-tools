"""Unit tests for the AV pipeline's pure pieces (no media / no Ollama needed)."""
from __future__ import annotations

import pandas as pd

from app.av.enrich import _coerce, _strip_attribution, build_prompt
from app.av.merge import NEW_COLUMNS, merge_results, output_filename
from app.av.models import Enrichment, FileResult, Segment, TranscriptStatus
from app.av.transcribe import _ts, to_rtf, to_srt


# ---- enrichment coercion / prefix stripping ----------------------------------

def test_strip_attribution():
    assert _strip_attribution("Gershwin's Rhapsody in Blue") == "Rhapsody in Blue"
    assert _strip_attribution("Robert Frost's The Road Not Taken") == "The Road Not Taken"
    assert _strip_attribution("The Grapes of Wrath") == "The Grapes of Wrath"


def test_coerce_buckets_and_strips():
    raw = {
        "content_description": "A cruise.",
        "suggested_title": "Spring Cruise",
        "suggested_date": "1941",
        "music_titles": ["Gershwin's Rhapsody in Blue"],
        "poem_titles": "Robert Frost's The Road Not Taken",  # string, not list
        "book_titles": ["The Grapes of Wrath"],
        "persons": ["Elsie", ""],
    }
    e = _coerce(raw)
    assert e.music_titles == ["Rhapsody in Blue"]
    assert e.poem_titles == ["The Road Not Taken"]
    assert e.book_titles == ["The Grapes of Wrath"]
    assert e.persons == ["Elsie"]            # blank dropped
    assert e.suggested_date == "1941"


def test_build_prompt_includes_existing():
    p = build_prompt("hello", {"title": "X", "date": "1941", "creator": ""})
    assert "EXISTING METADATA" in p and "title: X" in p
    assert "creator:" not in p              # empty values omitted from metadata


def test_build_prompt_includes_known_entities():
    p = build_prompt("hello", known_entities="Santa Cruz\nKenneth Patchen")
    assert "KNOWN ENTITIES" in p
    assert "Kenneth Patchen" in p


def test_build_prompt_omits_known_entities_when_blank():
    p = build_prompt("hello", known_entities="   ")
    assert "KNOWN ENTITIES" not in p


# ---- transcript serialization ------------------------------------------------

def test_srt_timestamp():
    assert _ts(0) == "00:00:00,000"
    assert _ts(3661.5) == "01:01:01,500"


def test_to_srt_and_rtf():
    segs = [Segment(0.0, 2.0, "Hello there."), Segment(2.0, 4.0, "Second line.")]
    srt = to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:02,000\nHello there." in srt
    assert "2\n00:00:02,000 --> 00:00:04,000\nSecond line." in srt
    rtf = to_rtf(segs)
    assert rtf.startswith("{\\rtf1")
    assert "Hello there. Second line." in rtf


# ---- CSV merge: additive, no overwrite, new rows -----------------------------

def _result(lid, status=TranscriptStatus.TRANSCRIBED, **enrich):
    return FileResult(
        local_identifier=lid, source_path=f"/m/{lid}.mp4",
        status=status, enrichment=Enrichment(**enrich),
    )


def test_merge_adds_columns_without_overwriting():
    original = pd.DataFrame(
        {"localIdentifier": ["a", "b"], "title": ["T1", "T2"], "date": ["1940", "1941"]}
    ).astype("string")
    results = [
        _result("a", suggested_title="New A", suggested_date="1940",
                content_description="desc a", music_titles=["Song"]),
        _result("b", suggested_title="New B"),
    ]
    merged = merge_results(original, results, id_column="localIdentifier")

    # originals untouched
    assert list(merged["title"]) == ["T1", "T2"]
    assert list(merged["date"]) == ["1940", "1941"]
    # new columns present and populated
    for col in NEW_COLUMNS:
        assert col in merged.columns
    assert merged.loc[merged["localIdentifier"] == "a", "music_titles"].iloc[0] == "Song"
    assert merged.loc[merged["localIdentifier"] == "a", "transcript_status"].iloc[0] == "transcribed"


def test_merge_appends_unmatched_files_as_new_rows():
    original = pd.DataFrame(
        {"localIdentifier": ["a"], "title": ["T1"]}
    ).astype("string")
    results = [_result("a"), _result("c", suggested_title="Orphan")]
    merged = merge_results(original, results, id_column="localIdentifier")
    assert set(merged["localIdentifier"]) == {"a", "c"}
    assert len(merged) == 2
    orphan = merged.loc[merged["localIdentifier"] == "c"]
    assert orphan["suggested_title"].iloc[0] == "Orphan"
    assert pd.isna(orphan["title"].iloc[0])     # no original data for new row


def test_merge_rejects_missing_join_column():
    original = pd.DataFrame({"id": ["a"]}).astype("string")
    try:
        merge_results(original, [_result("a")], id_column="localIdentifier")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_merge_includes_duration():
    from app.av.probe import format_duration
    original = pd.DataFrame(
        {"localIdentifier": ["a"], "title": ["T1"]}
    ).astype("string")
    r = FileResult(
        local_identifier="a", source_path="/m/a.mp4",
        status=TranscriptStatus.TRANSCRIBED,
        enrichment=Enrichment(),
        duration_seconds=125.0,   # 2:05
    )
    merged = merge_results(original, [r], id_column="localIdentifier")
    assert "duration" in merged.columns
    assert merged.loc[merged["localIdentifier"] == "a", "duration"].iloc[0] == "2:05"


def test_format_duration():
    from app.av.probe import format_duration
    assert format_duration(None) == ""
    assert format_duration(65.0) == "1:05"
    assert format_duration(3661.0) == "1:01:01"
    assert format_duration(0.0) == "0:00"


def test_output_filename_format():
    import datetime
    assert output_filename(datetime.date(2026, 6, 11)) == "AV_metadata_2026-06-11.csv"
