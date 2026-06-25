#!/usr/bin/env python3
"""Harvest object metadata for a private Merritt collection via its ATOM feed.

Walks the paginated recent.atom feed for a collection, collecting one record
per object (with its files), and writes both JSON and CSV. Optionally does a
second pass that fetches each object's system/mrt-ingest.txt to read its
localIdentifier (one extra request per object).

The Merritt feed authenticates with a Rails session cookie, NOT HTTP Basic
auth (the dashboard login also sits behind an AWS WAF JS challenge that a
plain HTTP client can't solve). So instead of a password, this script replays
the session cookie from a browser where you've already logged in:

  1. Log in to https://merritt.cdlib.org in your browser.
  2. Open DevTools -> Application (Chrome) / Storage (Firefox) -> Cookies
     -> https://merritt.cdlib.org, and copy the VALUE of the cookie named
     `_mrt-dash_session`.
  3. Run this script and paste that value at the prompt.

The cookie is prompted via getpass (hidden, kept out of shell history) and is
never written to disk. Sessions expire, so if you get a 401, log in again and
grab a fresh cookie value. Run from your own terminal so the prompt can read
your input:

    python merritt_harvest.py

Dependencies: requests, feedparser  (see requirements.txt)
"""

import csv
import getpass
import json
import os
import re
import sys
from urllib.parse import urljoin

import feedparser
import requests

DEFAULT_ARK = "ark:/13030/m5jr2679"
HOST = "https://merritt.cdlib.org"
BASE = f"{HOST}/object/recent.atom"
SESSION_COOKIE = "_mrt-dash_session"
INGEST_FILE = "system/mrt-ingest.txt"
UNASSIGNED = "(:unas)"  # Merritt's placeholder for an empty field

DEFAULT_BASENAME = "merritt_collection"
OUTPUT_DIR = "outputs"  # gitignored, so private metadata isn't committed

# `ark:/...` embedded in the entry id (e.g. "http://n2t.net/ark:/13030/m59421hf").
ARK_RE = re.compile(r"ark:/\S+")
# Version is the path segment after the (encoded) ark in a presign-file href:
#   /api/presign-file/<encoded-ark>/<version>/<path>
VERSION_RE = re.compile(r"/api/presign-file/[^/]+/(\d+)/")


def get_session_cookie():
    value = getpass.getpass(f"Paste the {SESSION_COOKIE} cookie value (hidden): ").strip()
    if not value:
        sys.exit("No cookie entered; aborting.")
    return value


def get_collection_ark():
    val = input(f"Collection ARK [{DEFAULT_ARK}]: ").strip() or DEFAULT_ARK
    return val


def get_output_basename():
    name = input(
        f"Name for the output files (no extension) [{DEFAULT_BASENAME}]: "
    ).strip() or DEFAULT_BASENAME
    # Tolerate a typed .json/.csv extension.
    for ext in (".json", ".csv"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    return name


def bare_ark(object_id):
    """Strip the resolver prefix: http://n2t.net/ark:/... -> ark:/..."""
    m = ARK_RE.search(object_id or "")
    return m.group(0) if m else object_id


def file_category(link):
    """Classify a file link: object_zip | system | producer."""
    if link.get("rel") == "alternate":
        return "object_zip"  # whole-object download, not a member file
    title = link.get("title") or ""
    if title.startswith("system/"):
        return "system"  # Merritt/BagIt internal files
    return "producer"  # actual deposited content


def object_version(files):
    for f in files:
        m = VERSION_RE.search(f.get("href") or "")
        if m:
            return m.group(1)
    return None


def parse_entry(entry):
    """Flatten one ATOM entry into an object record plus its file links."""
    files = []
    for link in entry.get("links", []):
        # Skip navigation/self links; keep file (enclosure/alternate) links.
        if link.get("rel") in ("self", "next", "previous", "first", "last"):
            continue
        files.append(
            {
                "href": link.get("href"),
                "type": link.get("type"),
                "length": link.get("length"),
                "title": link.get("title"),
                "rel": link.get("rel"),
                "category": file_category(link),
            }
        )
    object_id = entry.get("id")
    return {
        "object_ark": object_id,
        "bare_ark": bare_ark(object_id),
        "local_identifier": None,  # filled in later from mrt-ingest.txt
        "version": object_version(files),
        "title": entry.get("title"),
        "author": entry.get("author"),
        "updated": entry.get("updated"),
        "published": entry.get("published"),
        "summary": entry.get("summary"),
        "files": files,
    }


def next_url(feed):
    for link in feed.feed.get("links", []):
        if link.get("rel") == "next":
            return link.get("href")
    return None


def build_session(cookie_value):
    session = requests.Session()
    # Send the cookie as a raw header so requests' cookie jar can't re-quote a
    # value containing %, =, or -- (which _mrt-dash_session does).
    session.headers["Cookie"] = f"{SESSION_COOKIE}={cookie_value}"
    return session


def harvest(session, ark):
    url = f"{BASE}?collection={ark}"
    objects = []
    page = 0

    while url:
        page += 1
        resp = session.get(url, timeout=60)
        if resp.status_code == 401:
            waf = resp.headers.get("x-amzn-waf-action")
            print("--- 401 diagnostics ---", file=sys.stderr)
            print(f"  x-amzn-waf-action: {waf}", file=sys.stderr)
            print(f"  content-type: {resp.headers.get('content-type')}", file=sys.stderr)
            print(f"  body[:200]: {resp.text[:200]!r}", file=sys.stderr)
            sys.exit("401 Unauthorized — session cookie missing/expired or not "
                     "accepted. Log in again at merritt.cdlib.org and paste a "
                     f"fresh {SESSION_COOKIE} value.")
        resp.raise_for_status()

        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            sys.exit(f"Could not parse feed at {url}: {feed.bozo_exception}")

        for entry in feed.entries:
            objects.append(parse_entry(entry))
        print(f"  page {page}: {len(feed.entries)} objects "
              f"(running total {len(objects)})")

        # The feed's `next` link is relative; resolve it against this page's URL.
        nxt = next_url(feed)
        url = urljoin(resp.url, nxt) if nxt else None

    return objects


def ingest_href(obj):
    """Find the object's system/mrt-ingest.txt download link, if present."""
    for f in obj["files"]:
        if f.get("title") == INGEST_FILE:
            return f.get("href")
    return None


def parse_local_identifier(text):
    """Pull the localIdentifier value out of an mrt-ingest.txt body.

    The file is tab-separated `key:<TAB>value` lines. Split on the first tab
    (not the colon — values like collection: and timestamps contain colons).
    Merritt writes "(:unas)" when a field is unset; treat that as no value.
    """
    for line in text.splitlines():
        key, sep, value = line.partition("\t")
        if not sep:
            continue
        if key.rstrip(":").strip().lower() == "localidentifier":
            value = value.strip()
            return None if value in ("", UNASSIGNED) else value
    return None


def enrich_local_identifiers(session, objects):
    """Second pass: fetch each object's ingest file and read its localIdentifier.

    One extra request per object, so this is the slow part. Stops gracefully if
    the session expires, leaving already-fetched values in place so the run can
    still be written out (re-run with a fresh cookie to fill the rest).
    """
    total = len(objects)
    print(f"Fetching localIdentifier for {total} objects "
          "(one request each; this can take a while)...")
    for i, obj in enumerate(objects, 1):
        href = ingest_href(obj)
        if not href:
            continue
        try:
            resp = session.get(urljoin(HOST, href), timeout=60)
            if resp.status_code == 401:
                print(f"  session expired at object {i}/{total}; keeping what "
                      "we have. Re-run with a fresh cookie to finish the rest.",
                      file=sys.stderr)
                break
            resp.raise_for_status()
            obj["local_identifier"] = parse_local_identifier(resp.text)
        except requests.RequestException as exc:
            print(f"  warn: {obj['bare_ark']}: {exc}", file=sys.stderr)
        if i % 100 == 0 or i == total:
            print(f"  enriched {i}/{total}")


def _to_int(value):
    """File lengths arrive as strings; treat missing/blank as 0 for summing."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def write_outputs(objects, basename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_json = os.path.join(OUTPUT_DIR, f"{basename}.json")
    out_csv = os.path.join(OUTPUT_DIR, f"{basename}.csv")

    # JSON keeps the complete records (all files + every field).
    with open(out_json, "w") as fh:
        json.dump(objects, fh, indent=2)

    # CSV is the trimmed view: ONE row per object, aggregating producer files
    # only (system files and the whole-object zip are excluded). total_file_length
    # sums the producer file sizes; file_types lists their unique MIME types.
    fields = [
        "bare_ark", "local_identifier", "object_ark", "version", "title",
        "total_file_length", "file_types",
    ]
    with open(out_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for obj in objects:
            producer = [f for f in obj["files"] if f.get("category") == "producer"]
            total_len = sum(_to_int(f.get("length")) for f in producer)
            types = sorted({f.get("type") for f in producer if f.get("type")})
            writer.writerow(
                {
                    "bare_ark": obj["bare_ark"],
                    "local_identifier": obj["local_identifier"],
                    "object_ark": obj["object_ark"],
                    "version": obj["version"],
                    "title": obj["title"],
                    "total_file_length": total_len,
                    "file_types": ", ".join(types),
                }
            )
    return out_json, out_csv


def main():
    ark = get_collection_ark()
    basename = get_output_basename()
    want_local_id = input(
        "Also fetch localIdentifier from each object's ingest file? "
        "(slower, one request per object) [Y/n]: "
    ).strip().lower() not in ("n", "no")
    cookie_value = get_session_cookie()
    session = build_session(cookie_value)

    print(f"Harvesting collection {ark}")
    objects = harvest(session, ark)
    if want_local_id:
        enrich_local_identifiers(session, objects)

    out_json, out_csv = write_outputs(objects, basename)
    print(f"\nDone: {len(objects)} objects")
    print(f"  {out_json}  (full records)")
    print(f"  {out_csv}  (one row per object, producer files aggregated)")


if __name__ == "__main__":
    main()
