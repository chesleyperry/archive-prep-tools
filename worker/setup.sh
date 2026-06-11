#!/usr/bin/env bash
# Create the Python 3.12 transcription worker venv and install its deps.
# Two hard requirements on this machine:
#   1. Python 3.12, not the host's 3.14 — faster-whisper/mlx wheels lag 3.14.
#   2. NATIVE arm64, not the x86_64 (Rosetta) Homebrew python at /usr/local —
#      mlx-whisper is Apple-Silicon-only and won't install under x86_64.
# So we default to the arm64 Homebrew python at /opt/homebrew.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-/opt/homebrew/bin/python3.12}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found. Install it with:" >&2
  echo "  arch -arm64 /opt/homebrew/bin/brew install python@3.12" >&2
  echo "or set PYTHON=/path/to/arm64/python3.12" >&2
  exit 1
fi

ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
if [ "$ARCH" != "arm64" ]; then
  echo "error: $PYTHON is $ARCH, but mlx-whisper needs native arm64." >&2
  exit 1
fi

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "worker venv ready: $(.venv/bin/python --version)"
