"""Shared dataclasses for the AV pipeline.

Plain dataclasses (not pydantic) so the pipeline stays framework-free and
unit-testable without FastAPI — same convention as backend/app/models.py.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TranscriptStatus(str, Enum):
    """Why/whether a file produced a transcript. Stored in the CSV verbatim."""

    TRANSCRIBED = "transcribed"
    PARTIAL = "partial — music segments skipped"
    MUSIC_ONLY = "music only — not transcribed"
    NO_SPEECH = "no speech detected"
    NO_AUDIO = "no audio track"
    ERROR = "error"


@dataclass
class Segment:
    """One timed chunk of audio. ``kind`` is "speech" or "music"."""

    start: float          # seconds
    end: float            # seconds
    text: str             # transcript text ("" for music segments)
    kind: str = "speech"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Enrichment:
    """LLM-suggested metadata. All fields optional; lists may be empty."""

    content_description: str = ""
    suggested_title: str = ""
    suggested_date: str = ""
    persons: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    music_titles: list[str] = field(default_factory=list)
    poem_titles: list[str] = field(default_factory=list)
    book_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class FileResult:
    """Everything produced for a single media file."""

    local_identifier: str            # filename without extension
    source_path: str
    status: TranscriptStatus
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None
    enrichment: Enrichment | None = None
    outputs: list[str] = field(default_factory=list)   # written file paths
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_identifier": self.local_identifier,
            "source_path": self.source_path,
            "status": self.status.value,
            "language": self.language,
            "enrichment": self.enrichment.to_dict() if self.enrichment else None,
            "outputs": self.outputs,
            "error": self.error,
        }
