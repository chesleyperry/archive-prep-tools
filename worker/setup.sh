#!/usr/bin/env bash
# Create the Python 3.12 transcription worker venv and install its deps.
# faster-whisper / ctranslate2 lack reliable wheels for the host's Python 3.14,
# so the worker runs in its own 3.12 interpreter (see ../requirements.txt).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.12}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found. Install Python 3.12 or set PYTHON=..." >&2
  exit 1
fi

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "worker venv ready: $(.venv/bin/python --version)"
