#!/usr/bin/env bash
# Start the Archive Prep Tools web server.
# Then open http://127.0.0.1:8000 in your browser. Press Control-C to stop.
set -euo pipefail
cd "$(dirname "$0")/backend"

echo "Starting Archive Prep Tools..."
echo "  Open this in your browser:  http://127.0.0.1:8000"
echo "  (Press Control-C in this window to stop the server.)"
echo
exec env PYTHONPATH=. ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
