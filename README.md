# Archive Prep Tools

A small suite for preparing audiovisual and tabular archive materials. Everything
runs **locally on your own Mac** — your files and audio never leave the machine.

| Tool | Type | What it does |
| --- | --- | --- |
| **AV File Access Preparation** | Web | Transcribes a folder of audio/video, writes a short description and transcript (SRT/RTF) per file, extracts names/places/titles, and builds one enriched metadata CSV. |
| **Data-Prep Tool** | Web | Checks a CSV or Google Sheet for quality problems, plans duplicate merges, and generates a README + data dictionary. |
| **Merritt Harvester** | Command line | Pulls collection metadata from a private Merritt collection into CSV/JSON. |
| **Merritt File Summary** | Command line | Summarizes a harvested collection: per-object producer file counts, total sizes, file types, and content dates. |
| **Item Folder Builder** | Command line | Sorts modified TIFFs, original TIFFs and derivative JPEGs into one folder per item and adds a Dublin Core XML file made from a metadata spreadsheet. |

The two web tools share one web server and one home page; the Merritt harvester is
a Terminal script.

The tools were created with Claude Code AI, though they run locally and do not submit any recordings, collection materials, or metadata to Claude.  They were created during the **DH Programming Pedagogy in the Age of AI** course during DHSI 2026, taught by Anastasia Salter & John T. Murray, June 8–12, Montréal.



---

## 1. One-time setup

You need a Mac with **[Homebrew](https://brew.sh)** installed. Then:

```bash
# Install the supporting programs (once):
brew install ffmpeg                 # needed to read audio/video
arch -arm64 /opt/homebrew/bin/brew install python@3.12   # native Apple-Silicon Python for transcription

# Install Ollama for the AV tool's summaries (once):
#   1. Download from https://ollama.com and open it
#   2. In Terminal:  ollama pull qwen2.5

# From inside this project folder, set up the tools (once):
./setup.sh
```

`./setup.sh` creates the two Python environments the tools need and installs
everything into them. It does not touch the rest of your system.

> **Why two Python environments?** The web server runs on your system Python,
> while transcription runs in a separate, native Apple-Silicon Python 3.12 so it
> can use your Mac's GPU. `setup.sh` handles both for you.

---

## 2. Start the web tools

```bash
./start.sh
```

Then open **http://127.0.0.1:8000** in your browser. You'll see the home page with
a link to each web tool. Leave the Terminal window open while you work; press
**Control-C** in it to stop the server when you're done.

> For the AV tool, make sure **Ollama is running** first (open the Ollama app, or
> run `ollama list` to check).

---

## 3. Using each tool

### AV File Access Preparation

From the home page, click **Open tool** under *AV File Access Preparation*, then:

1. **Input directory** — the full path to your folder of `.mp3` / `.mp4` files.
2. **Output directory** — where the results should be written.
3. **Metadata CSV** (optional) — your existing spreadsheet. It is matched to the
   media files on the **`localIdentifier`** column (the filename without its
   extension) and the tool **adds new columns without changing your originals**.
4. **Whisper model** — `small` is a good balance; `large-v3` is most accurate but
   slower; `tiny`/`base` are fastest.
5. Click **Start batch** and watch the progress bar.

For each file it writes, into your output folder:

- `NAME_transcript.srt` and `NAME_transcript.rtf` — the transcript
- `NAME_summary.txt` — a 3-sentence content description
- `AV_metadata_<date>.csv` — your CSV plus new columns: suggested title/date,
  description, people, places, music/poem/book titles, and a `transcript_status`

Files with no speech (silent reels, no audio track) are handled gracefully —
they skip the transcript files and note why in `transcript_status`.

> The very first run downloads the transcription model once (about a minute),
> then later files run quickly.

### Data-Prep Tool

From the home page, click **Open tool** under *Data-Prep Tool*, then upload a CSV
(or paste a Google Sheet URL), optionally name the columns to match duplicates
on, and click **Analyze**. Download the generated README and cleaned CSV from the
results page. Your original file is never modified.

Deeper reference (architecture, adding checks, Google Sheets OAuth) is in
[`docs/data-prep.md`](docs/data-prep.md).

### Merritt Harvester

This one runs in Terminal (no web page). In a Terminal window:

```bash
.venv/bin/python merritt_harvest.py
```

It will ask you to paste a Merritt session cookie. To get it:

1. Log in to **https://merritt.cdlib.org** in your browser.
2. Open DevTools → Application/Storage → Cookies → `https://merritt.cdlib.org`.
3. Copy the **value** of the cookie named `_mrt-dash_session` and paste it when
   prompted (the prompt hides what you type). Cookies expire, so grab a fresh one
   each session.

The harvester saves its results into an `outputs/` folder (one `.csv` and one
`.json` per collection).

### Merritt File Summary

A companion to the Merritt Harvester. After you've harvested a collection, this
makes a one-row-per-object summary of its **producer files** (the content you
deposited, not Merritt's own system files). In a Terminal window:

```bash
.venv/bin/python merritt_file_summary.py
```

Then:

1. It lists the harvest `.json` files in your `outputs/` folder — type the
   **number** of the one you want to summarize.
2. It asks whether to add each object's **content date** (for example `1967`):
   - Press **Enter** (yes) to include it. The date is looked up on Merritt, so it
     asks for your `_mrt-dash_session` cookie (same as the harvester above) and
     does one quick lookup per object — slower on large collections.
   - Type **n** to skip the date for a fast, offline run (the date column is left
     blank).

It saves a new spreadsheet next to the JSON, named `<name>_file_summary.csv`, with
one row per object:

| Column | Meaning |
| --- | --- |
| `bare_ark` | the object's identifier |
| `local_identifier` | your local ID for the item |
| `title` | the object title |
| `date` | the content's date (blank unless you included it) |
| `author` | the author, if recorded |
| `producer_file_count` | how many producer files the object has |
| `producer_total_bytes` | the producer files' sizes added up, in bytes |
| `permanent link` | the object's stable web address |
| `producer_file_types` | the kinds of files present (e.g. audio, image) |
| `producer_total_readable` | the same total size shown as KB / MB / GB |

If your login expires partway through a long run, it stops cleanly and keeps what
it already found — just run it again with a fresh cookie.

### Item Folder Builder

This one also runs in Terminal. It needs only the Python that comes with the Mac:

```bash
/usr/bin/python3 prepare_items.py
```

It asks for the modified-TIFF folder, the original-TIFF folder, the derivative-JPEG
folder, your metadata spreadsheet (saved as CSV) and the folder where the new
folders should go. If a file set adds a tag to the item name (for example
`name_orig.tif`), it also asks for that tag. Then, for each item, it:

1. creates a folder named after the item,
2. moves the three image files into it, and
3. writes `itemname.xml` in Dublin Core format from that item's spreadsheet row.

Column A of the spreadsheet is the item name. The other column headings are
translated to Dublin Core using [`dublin_core_mapping.csv`](dublin_core_mapping.csv),
which must stay next to the script. Before changing anything it prints a report of
problems (missing files, names that don't match, spreadsheet columns not in the
mapping) and waits for you to type `yes`; items with problems are left alone.

Two smaller scripts do the same job in separate steps:
`sort_into_folders.py` (TIFF + JPEG into folders) and `spreadsheet_to_xml.py`
(spreadsheet rows to XML files in existing folders).

---

## Notes

- **Everything is local.** No audio, video, or spreadsheet data is sent to any
  outside service. Summaries use the local Ollama model on your machine.
- **Outputs** go wherever you point the tools — your originals are never changed.
- Developer details (code layout, tests) live in [`backend/`](backend/) and
  [`docs/data-prep.md`](docs/data-prep.md).
