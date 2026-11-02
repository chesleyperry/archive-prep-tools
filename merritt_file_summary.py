#!/usr/bin/env python3
"""Summarize the producer files in a Merritt harvest JSON file.

Reads one of the .json files produced by merritt_harvest.py and, for each
record (one object), writes a row with its descriptive fields plus:
  - producer_file_count     how many producer (deposited) files it has
  - producer_total_bytes     the summed size of those producer files, in bytes
  - producer_total_readable  the same size shown as KB / MB / GB
  - producer_file_types      the unique file types among its producer files

It can also add a `date` column holding each object's content date (the ERC
"when" value, e.g. 1967). That date is NOT in the saved JSON, so it is fetched
live from each object's system/mrt-erc.txt on Merritt -- which needs your login
cookie and does one small download per object. You can skip that step for a
quick, offline run (the date column is then left blank).

System files and the whole-object zip are ignored, matching the harvester.
Output is a CSV written next to the JSON, named <name>_file_summary.csv.

Run it from the project folder:
    .venv/bin/python merritt_file_summary.py
"""

import csv
import json
import os
import sys
from urllib.parse import urljoin

# Reuse the harvester's login handling so there's only one cookie setup.
from merritt_harvest import HOST, build_session, get_session_cookie

OUTPUT_DIR = "outputs"
ERC_FILE = "system/mrt-erc.txt"
UNASSIGNED = "(:unas)"  # Merritt's placeholder for an empty field


def human_size(num_bytes):
    """Turn a byte count into a short readable string like '1.42 GB'."""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.2f} {unit}"
        size /= 1024


def to_int(value):
    """File lengths arrive as strings; treat missing/blank as 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def erc_href(rec):
    """Find the object's system/mrt-erc.txt download link, if present."""
    for f in rec.get("files", []):
        if f.get("title") == ERC_FILE:
            return f.get("href")
    return None


def parse_erc_date(text):
    """Pull the content date (the ERC 'when' value) from an mrt-erc.txt body.

    The file is `label: value` lines; the date is the `when:` line. Merritt
    writes "(:unas)" when a field is unset; treat that as no value.
    """
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.strip().lower() == "when":
            value = value.strip()
            return None if value in ("", UNASSIGNED) else value
    return None


def pick_json():
    """Let the user choose a JSON file from outputs/ by number, or paste a path."""
    try:
        files = sorted(
            f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".json")
        )
    except FileNotFoundError:
        files = []
    if files:
        print(f"JSON files in {OUTPUT_DIR}/:")
        for i, name in enumerate(files, 1):
            print(f"  {i}. {name}")
        choice = input("Pick a number (or paste a full path to a JSON file): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return os.path.join(OUTPUT_DIR, files[int(choice) - 1])
        path = choice
    else:
        path = input("Paste the full path to a harvest JSON file: ").strip()
    if not path:
        sys.exit("No file chosen; aborting.")
    if not os.path.isfile(path):
        sys.exit(f"Could not find a file at: {path}")
    return path


def fetch_dates(records, session):
    """Fill each record's content date from its mrt-erc.txt on Merritt.

    One small download per object. Stops gracefully if the login expires,
    leaving already-fetched dates in place (re-run with a fresh cookie to
    finish the rest).
    """
    total = len(records)
    print(f"Fetching content date for {total} objects "
          "(one request each; this can take a while)...")
    for i, rec in enumerate(records, 1):
        href = erc_href(rec)
        if not href:
            continue
        try:
            resp = session.get(urljoin(HOST, href), timeout=60)
            if resp.status_code == 401:
                print(f"  login expired at object {i}/{total}; keeping what we "
                      "have. Re-run with a fresh cookie to finish the rest.",
                      file=sys.stderr)
                break
            resp.raise_for_status()
            rec["_content_date"] = parse_erc_date(resp.text)
        except Exception as exc:  # noqa: BLE001 - keep going on any one object
            print(f"  warn: {rec.get('bare_ark')}: {exc}", file=sys.stderr)
        if i % 100 == 0 or i == total:
            print(f"  fetched {i}/{total}")


def main():
    path = pick_json()
    want_date = input(
        "Add each object's content date from Merritt? "
        "(needs your login; one download per object) [Y/n]: "
    ).strip().lower() not in ("n", "no")

    with open(path) as fh:
        records = json.load(fh)

    if want_date:
        cookie_value = get_session_cookie()
        session = build_session(cookie_value)
        fetch_dates(records, session)

    base = os.path.splitext(os.path.basename(path))[0]
    out_csv = os.path.join(OUTPUT_DIR, f"{base}_file_summary.csv")

    fields = [
        "bare_ark", "local_identifier", "title", "date", "author",
        "producer_file_count", "producer_total_bytes", "permanent link",
        "producer_file_types", "producer_total_readable",
    ]

    grand_files = 0
    grand_bytes = 0
    with open(out_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            producer = [
                f for f in rec.get("files", []) if f.get("category") == "producer"
            ]
            count = len(producer)
            total = sum(to_int(f.get("length")) for f in producer)
            types = sorted({f.get("type") for f in producer if f.get("type")})
            grand_files += count
            grand_bytes += total
            writer.writerow(
                {
                    "bare_ark": rec.get("bare_ark"),
                    "local_identifier": rec.get("local_identifier"),
                    "title": rec.get("title"),
                    "date": rec.get("_content_date"),
                    "author": rec.get("author"),
                    "producer_file_count": count,
                    "producer_total_bytes": total,
                    "permanent link": rec.get("object_ark"),
                    "producer_file_types": ", ".join(types),
                    "producer_total_readable": human_size(total),
                }
            )

    print(f"\nDone: {len(records)} objects summarized")
    print(f"  producer files, all objects: {grand_files}")
    print(f"  producer size,  all objects: {grand_bytes} bytes ({human_size(grand_bytes)})")
    print(f"  wrote {out_csv}")


if __name__ == "__main__":
    main()
