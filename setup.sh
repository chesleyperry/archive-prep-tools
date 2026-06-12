#!/usr/bin/env bash
# One-time setup for Archive Prep Tools. Run this once after cloning.
# Creates the two Python environments the tools need and installs everything.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Setting up the web-server environment..."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "==> Setting up the transcription worker (for the AV tool)..."
bash worker/setup.sh

cat <<'DONE'

Setup complete.

Still needed for the AV tool (install once, outside this script):
  - ffmpeg   : brew install ffmpeg
  - Ollama   : https://ollama.com  (then run:  ollama pull qwen2.5)

Start the tools with:   ./start.sh
DONE
