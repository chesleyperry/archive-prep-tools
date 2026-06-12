"""LLM enrichment via a local Ollama model (host side).

One JSON-mode call per file turns the transcript + the file's existing CSV row
into a 3-sentence description, a suggested title/date, and bucketed proper
nouns. Default model ``qwen2.5:latest`` — fastest and most accurate in the
head-to-head, with correct song/poem/book discrimination and clean JSON.
Nothing leaves the machine.
"""
from __future__ import annotations

import json
import re

import requests

from app.av.models import Enrichment

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:latest"

# Strips a leading possessive attribution, e.g. "Gershwin's Rhapsody in Blue"
# -> "Rhapsody in Blue", "Robert Frost's The Road Not Taken" -> "The Road...".
_POSSESSIVE = re.compile(r"^(?:[A-Z][\w.\-]*\.?\s+){0,4}[A-Z][\w.\-]*['’]s\s+")

_SYSTEM = (
    "You are a metadata extraction assistant for an audiovisual archive. "
    "Read the TRANSCRIPT (and any EXISTING METADATA) and return ONLY a JSON "
    "object with exactly these keys: \"content_description\" (a 3-sentence plain "
    "summary), \"suggested_title\", \"suggested_date\" (best date or date range "
    "mentioned, normalized to digits where possible, else \"\"), \"persons\", "
    "\"places\", \"music_titles\", \"poem_titles\", \"book_titles\". "
    "Only include an entity if it is actually present. Do not confuse a song "
    "with a poem with a book. Title fields should be bare titles without the "
    "creator's name. If the transcript is empty, base suggestions only on the "
    "existing metadata and leave entity arrays empty."
)

_LIST_KEYS = ("persons", "places", "music_titles", "poem_titles", "book_titles")
_TITLE_KEYS = ("music_titles", "poem_titles", "book_titles")


def _strip_attribution(title: str) -> str:
    return _POSSESSIVE.sub("", title.strip()).strip()


def build_prompt(
    transcript: str,
    existing: dict[str, str] | None = None,
    known_entities: str = "",
) -> str:
    parts = [_SYSTEM, ""]
    if existing:
        meta = "; ".join(f"{k}: {v}" for k, v in existing.items() if v)
        if meta:
            parts += ["EXISTING METADATA:", meta, ""]
    if known_entities.strip():
        parts += [
            "KNOWN ENTITIES — spelling guide only. Use these exact spellings IF the entity"
            " appears in the transcript. Do NOT include any entity that is not actually"
            " mentioned in the transcript.",
            known_entities.strip(),
            "",
        ]
    parts += ["TRANSCRIPT:", transcript.strip() or "(no speech / empty transcript)"]
    return "\n".join(parts)


def _coerce(raw: dict) -> Enrichment:
    def _as_list(v) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    lists = {k: _as_list(raw.get(k)) for k in _LIST_KEYS}
    for k in _TITLE_KEYS:
        lists[k] = [_strip_attribution(t) for t in lists[k]]
    return Enrichment(
        content_description=str(raw.get("content_description", "")).strip(),
        suggested_title=_strip_attribution(str(raw.get("suggested_title", ""))),
        suggested_date=str(raw.get("suggested_date", "")).strip(),
        **lists,
    )


def enrich(
    transcript: str,
    existing: dict[str, str] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: float = 120.0,
    known_entities: str = "",
) -> Enrichment:
    """Call the local model and return structured metadata.

    Raises ``requests.RequestException`` if Ollama is unreachable so the caller
    can record the failure per-file rather than aborting the batch.
    """
    payload = {
        "model": model,
        "prompt": build_prompt(transcript, existing, known_entities),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    response_text = resp.json().get("response", "{}")
    try:
        raw = json.loads(response_text)
    except json.JSONDecodeError:
        raw = {}
    return _coerce(raw if isinstance(raw, dict) else {})
