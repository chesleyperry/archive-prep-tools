#!/usr/bin/env python3
"""Harvest object metadata for a private Merritt collection via its ATOM feed.

Walks the paginated recent.atom feed for a collection, collecting one record
per object (with its files), and writes both JSON and CSV.

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
import re
import sys
from urllib.parse import urljoin

import feedparser
import requests

DEFAULT_ARK = "ark:/13030/m5jr2679"
BASE = "https://merritt.cdlib.org/object/recent.atom"
SESSION_COOKIE = "_mrt-dash_session"

OUT_JSON = "merritt_collection.json"
OUT_CSV = "merritt_collection.csv"

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


def harvest(cookie_value, ark):
    url = f"{BASE}?collection={ark}"
    objects = []
    page = 0
    session = requests.Session()
    # Send the cookie as a raw header so requests' cookie jar can't re-quote a
    # value containing %, =, or -- (which _mrt-dash_session does).
    session.headers["Cookie"] = f"{SESSION_COOKIE}={cookie_value}"

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


def write_outputs(objects):
    with open(OUT_JSON, "w") as fh:
        json.dump(objects, fh, indent=2)

    # CSV: one row per file, with the parent object's metadata repeated.
    # file_category lets you filter object_zip / system / producer in a sheet.
    fields = [
        "bare_ark", "object_ark", "version", "title", "updated", "published",
        "file_category", "file_rel", "file_title", "file_type", "file_length",
        "file_href",
    ]
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for obj in objects:
            rows = obj["files"] or [{}]  # emit a row even if no file links
            for f in rows:
                writer.writerow(
                    {
                        "bare_ark": obj["bare_ark"],
                        "object_ark": obj["object_ark"],
                        "version": obj["version"],
                        "title": obj["title"],
                        "updated": obj["updated"],
                        "published": obj["published"],
                        "file_category": f.get("category"),
                        "file_rel": f.get("rel"),
                        "file_title": f.get("title"),
                        "file_type": f.get("type"),
                        "file_length": f.get("length"),
                        "file_href": f.get("href"),
                    }
                )


def main():
    ark = get_collection_ark()
    cookie_value = get_session_cookie()
    print(f"Harvesting collection {ark}")
    objects = harvest(cookie_value, ark)
    write_outputs(objects)
    print(f"\nDone: {len(objects)} objects")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}  (one row per file)")


if __name__ == "__main__":
    main()
