"""Turn each row of a spreadsheet (saved as CSV) into an XML file inside the matching folder.

Run it with:  /usr/bin/python3 spreadsheet_to_xml.py
Column A of the sheet must hold the folder name. The XML file is named
after column A. Every other column heading is looked up in
dublin_core_mapping.csv (kept next to this script), which says which
Dublin Core element each heading becomes. Headings that are already Dublin
Core names (title, creator, "dc:title", "dcterms:created") also work.
Nothing is written until you have seen the report and typed "yes".
"""

import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def ask_for_path(question, want_folder):
    """Ask for a file or folder; dragging it into Terminal pastes its path."""
    while True:
        answer = input(question).strip().strip("'\"").replace("\\ ", " ")
        path = Path(answer).expanduser()
        if (want_folder and path.is_dir()) or (not want_folder and path.is_file()):
            return path
        print("  I can't find that. Please try again.")


DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
OAI_DC_NS = "http://www.openarchives.org/OAI/2.0/oai_dc/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DC_ELEMENTS = {
    "title", "creator", "subject", "description", "publisher", "contributor",
    "date", "type", "format", "identifier", "source", "language", "relation",
    "coverage", "rights",
}


def dublin_core_tag(heading):
    """Return the XML tag for a column heading, or None if it isn't Dublin Core."""
    text = heading.strip()
    lowered = text.lower()
    if lowered.startswith("dcterms:") or lowered.startswith("dcterms."):
        term = text[8:].strip()
        return f"{{{DCTERMS_NS}}}{term}" if re.fullmatch(r"[A-Za-z]+", term) else None
    if lowered.startswith("dc:") or lowered.startswith("dc."):
        lowered = lowered[3:].strip()
    return f"{{{DC_NS}}}{lowered}" if lowered in DC_ELEMENTS else None


def load_mapping(mapping_path):
    """Read the mapping sheet into {lowercase heading: XML tag}, plus notes about it."""
    mapping, notes = {}, []
    with open(mapping_path, newline="", encoding="utf-8-sig") as handle:
        for line_number, row in enumerate(csv.reader(handle), start=1):
            if line_number == 1 or len(row) < 2 or not row[0].strip():
                continue  # header line or blank line
            heading, target = row[0].strip().lower(), row[1].strip()
            term = re.sub(r"^dc(terms)?[:.]", "", target, flags=re.I).strip()
            if term.lower() in DC_ELEMENTS:
                tag = f"{{{DC_NS}}}{term.lower()}"
            elif re.fullmatch(r"[A-Za-z]+", term):
                # extent, rightsHolder, provenance etc. are not among the 15 basic elements
                tag = f"{{{DCTERMS_NS}}}{term}"
                note = f"'{row[0].strip()}' maps to {target}; written as dcterms:{term}"
                if note not in notes:
                    notes.append(note)
            else:
                notes.append(f"Mapping line {line_number} ('{target}') isn't usable and was ignored")
                continue
            if heading in mapping and mapping[heading] != tag:
                notes.append(f"Mapping line {line_number}: '{row[0].strip()}' is listed twice with different targets")
            mapping[heading] = tag
    return mapping, notes


ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)
ET.register_namespace("oai_dc", OAI_DC_NS)
ET.register_namespace("xsi", XSI_NS)


def main():
    print("Make one XML file per spreadsheet row and put it in the matching folder.\n")
    print("(Save your spreadsheet as a CSV file first: File > Download/Save as > CSV.)\n")
    mapping_path = Path(__file__).with_name("dublin_core_mapping.csv")
    if not mapping_path.is_file():
        mapping_path = ask_for_path(
            "Drag the Dublin Core mapping CSV here and press Return: ", want_folder=False
        )
    mapping, mapping_notes = load_mapping(mapping_path)
    csv_path = ask_for_path("Drag the CSV file here and press Return: ", want_folder=False)
    parent = ask_for_path(
        "Drag the folder that holds the sorted folders and press Return: ", want_folder=True
    )

    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        print("The spreadsheet has no data rows. Nothing to do.")
        return

    headings, data_rows = rows[0], rows[1:]
    tags = [mapping.get(h.strip().lower()) or dublin_core_tag(h) for h in headings]
    folders = {p.name: p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(".")}
    folders_lower = {name.lower(): name for name in folders}

    problems = []
    for index, tag in enumerate(tags[1:], start=1):
        if tag is None:
            problems.append(
                f"Column {index + 1} '{headings[index]}' isn't in the mapping sheet "
                "(this column will be left out of every XML file)"
            )
    jobs = {}  # folder name -> (sheet row number, row values)
    for row_number, row in enumerate(data_rows, start=2):
        if not any(cell.strip() for cell in row):
            continue  # skip completely blank rows
        name = row[0].strip() if row else ""
        if not name:
            problems.append(f"Row {row_number}: column A is empty")
        elif name in jobs:
            problems.append(
                f"Row {row_number}: '{name}' is a repeat of row {jobs[name][0]} (skipped)"
            )
        elif name not in folders:
            hint = ""
            if name.lower() in folders_lower:
                hint = f" (a folder named '{folders_lower[name.lower()]}' exists - capital letters differ)"
            problems.append(f"Row {row_number}: no folder named '{name}'{hint}")
        elif (folders[name] / f"{name}.xml").exists():
            problems.append(f"Row {row_number}: {name}.xml already exists (not overwritten)")
        else:
            jobs[name] = (row_number, row)

    sheet_names = {row[0].strip() for row in data_rows if row and row[0].strip()}
    for name in sorted(set(folders) - sheet_names):
        problems.append(f"Folder '{name}' has no row in the spreadsheet")

    if mapping_notes:
        print("\nNotes about the mapping sheet:")
        for note in mapping_notes:
            print("  -", note)

    print(f"\nFound {len(data_rows)} spreadsheet rows and {len(folders)} folders.")
    print(f"{len(jobs)} rows are ready to become XML files.")
    if problems:
        print(f"\n*** {len(problems)} PROBLEM(S) FOUND ***")
        for message in problems:
            print("  -", message)
        print("\nRows and folders with problems will be skipped.")

    if not jobs:
        print("\nNothing to write.")
        return
    answer = input(f"\nWrite {len(jobs)} XML files? Type yes to continue: ")
    if answer.strip().lower() != "yes":
        print("Okay, nothing was written.")
        return

    written = 0
    for name, (row_number, row) in jobs.items():
        record = ET.Element(f"{{{OAI_DC_NS}}}dc")
        record.set(
            f"{{{XSI_NS}}}schemaLocation",
            f"{OAI_DC_NS} http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        )
        for index, tag in enumerate(tags):
            if index == 0 or tag is None or index >= len(row) or not row[index].strip():
                continue  # column A is just the folder name; skip other/empty cells
            ET.SubElement(record, tag).text = row[index].strip()
        ET.indent(record)
        try:
            ET.ElementTree(record).write(
                folders[name] / f"{name}.xml", encoding="utf-8", xml_declaration=True
            )
            written += 1
        except OSError as error:
            print(f"  Could not write {name}.xml: {error}")

    print(f"\nDone. {written} XML files written.")
    if problems:
        print("Remember to look at the problems listed above.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(1)
