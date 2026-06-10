"""Google Sheets ingestion via OAuth (read-only).

This is a working scaffold. To enable it you need a Google Cloud project with
the Sheets API enabled and an OAuth client:

  1. https://console.cloud.google.com/ → create project
  2. Enable "Google Sheets API"
  3. Create OAuth 2.0 Client ID (type: Desktop or Web) → download as
     ``backend/secrets/client_secret.json``
  4. First run opens a browser consent screen; the token is cached in
     ``backend/secrets/token.json``.

Scope is read-only by design (agreed): the tool never writes to user sheets.
"""
from __future__ import annotations

import os
import re

import pandas as pd

# Read-only scope only.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

_SECRETS_DIR = os.path.join(os.path.dirname(__file__), "..", "secrets")
_CLIENT_SECRET = os.path.join(_SECRETS_DIR, "client_secret.json")
_TOKEN = os.path.join(_SECRETS_DIR, "token.json")

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_sheet_id(url_or_id: str) -> str:
    """Accept a full Sheets URL or a bare spreadsheet ID."""
    match = _SHEET_ID_RE.search(url_or_id)
    return match.group(1) if match else url_or_id.strip()


def _get_credentials():
    """Load cached OAuth creds, refreshing or running the consent flow as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(_TOKEN):
        creds = Credentials.from_authorized_user_file(_TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(_CLIENT_SECRET):
                raise FileNotFoundError(
                    "Missing OAuth client secret. See backend/app/google_sheets.py "
                    "for setup steps, then place client_secret.json in backend/secrets/."
                )
            flow = InstalledAppFlow.from_client_secrets_file(_CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(_SECRETS_DIR, exist_ok=True)
        with open(_TOKEN, "w") as fh:
            fh.write(creds.to_json())
    return creds


def load_sheet(url_or_id: str, sheet_range: str = "A1:ZZ") -> pd.DataFrame:
    """Fetch a Google Sheet's first tab into a DataFrame (header = first row)."""
    from googleapiclient.discovery import build

    spreadsheet_id = extract_sheet_id(url_or_id)
    creds = _get_credentials()
    service = build("sheets", "v4", credentials=creds)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_range)
        .execute()
    )
    values = result.get("values", [])
    if not values:
        raise ValueError("Sheet appears to be empty.")
    header, *rows = values
    # pad short rows so every record has every column
    padded = [r + [None] * (len(header) - len(r)) for r in rows]
    return pd.DataFrame(padded, columns=header).astype("string")
