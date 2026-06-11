"""AV File Access Preparation.

Local-first pipeline that turns a directory of audio/video files plus a minimal
metadata CSV into access derivatives: transcripts (SRT/RTF), short content
descriptions, and an enriched batch metadata CSV.

Everything runs on-machine: ffmpeg for audio, a Python 3.12 worker venv for
transcription (faster-whisper), and a local Ollama model for summary/entity
extraction. See backend/app/av/pipeline.py for the per-file orchestration.
"""
