"""Build one folder per item from three sets of files plus a metadata spreadsheet.

Run it with:  /usr/bin/python3 prepare_items.py

You give it: the modified TIFFs, the original TIFFs, the derivative JPEGs, the
metadata spreadsheet (saved as CSV) and the folder where the new folders go.
For every item it creates a folder named after the item, moves the three files
into it, and writes a Dublin Core XML file made from the item's spreadsheet row.
Column A of the sheet is the item name. Column headings are translated to
Dublin Core using dublin_core_mapping.csv (kept next to this script).
Nothing is changed until you have seen the report and typed "yes".
"""

import csv
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
OAI_DC_NS = "http://www.openarchives.org/OAI/2.0/oai_dc/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DC_ELEMENTS = {
    "title", "creator", "subject", "description", "publisher", "contributor",
    "date", "type", "format", "identifier", "source", "language", "relation",
    "coverage", "rights",
}
TIF_EXTENSIONS = {".tif", ".tiff"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}

ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)
ET.register_namespace("oai_dc", OAI_DC_NS)
ET.register_namespace("xsi", XSI_NS)


def ask_for_path(question, want_folder):
    """Ask for a file or folder; dragging it into Terminal pastes its path."""
    while True:
        answer = input(question).strip().strip("'\"").replace("\\ ", " ")
        path = Path(answer).expanduser()
        if (want_folder and path.is_dir()) or (not want_folder and path.is_file()):
            return path
        print("  I can't find that. Please try again.")


def dublin_core_tag(heading):
    """Return the XML tag for a heading that is already a Dublin Core name, else None."""
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
                notes.append(
                    f"Mapping line {line_number}: '{row[0].strip()}' is listed twice with different targets"
                )
            mapping[heading] = tag
    return mapping, notes


def collect(label, folder, extensions, suffix):
    """Return ({item name: file}, [problem messages]) for one set of files."""
    found, problems = {}, []
    for item in sorted(folder.iterdir()):
        if item.name.startswith(".") or not item.is_file():
            continue
        if item.suffix.lower() not in extensions:
            problems.append(f"Unexpected file type in the {label} folder: {item.name}")
            continue
        name = item.stem
        if suffix:
            if not name.lower().endswith(suffix.lower()):
                problems.append(f"{label}: {item.name} doesn't end with '{suffix}'")
                continue
            name = name[: -len(suffix)]
        if name in found:
            problems.append(
                f"{label}: two files for '{name}': {found[name].name} and {item.name}"
            )
            continue
        found[name] = item
    return found, problems


def near_miss(name, known_names):
    """If another name differs only by capital letters, say so."""
    for other in known_names:
        if other != name and other.lower() == name.lower():
            return f" (a similar name '{other}' exists - capital letters differ)"
    return ""


def build_xml(tags, row):
    record = ET.Element(f"{{{OAI_DC_NS}}}dc")
    record.set(
        f"{{{XSI_NS}}}schemaLocation",
        f"{OAI_DC_NS} http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
    )
    for index, tag in enumerate(tags):
        if index == 0 or tag is None or index >= len(row) or not row[index].strip():
            continue  # column A is just the item name; skip other/empty cells
        ET.SubElement(record, tag).text = row[index].strip()
    ET.indent(record)
    return ET.ElementTree(record)


def main():
    print("Build one folder per item: files + Dublin Core XML.\n")
    mapping_path = Path(__file__).with_name("dublin_core_mapping.csv")
    if not mapping_path.is_file():
        mapping_path = ask_for_path(
            "Drag the Dublin Core mapping CSV here and press Return: ", want_folder=False
        )
    mapping, mapping_notes = load_mapping(mapping_path)

    mod_folder = ask_for_path("Drag the MODIFIED TIFF folder here and press Return: ", True)
    orig_folder = ask_for_path("Drag the ORIGINAL TIFF folder here and press Return: ", True)
    jpeg_folder = ask_for_path("Drag the DERIVATIVE JPEG folder here and press Return: ", True)
    csv_path = ask_for_path(
        "Drag the metadata spreadsheet (CSV) here and press Return: ", False
    )
    out_folder = ask_for_path(
        "Drag the folder where the new folders should be created and press Return: ", True
    )

    print("\nIf a file set adds a tag to the item name (for example name_orig.tif),")
    print("type that tag below, including any underscore. Press Return if there is none.")
    mod_suffix = input("  Tag on MODIFIED TIFF names (e.g. _mod): ").strip()
    orig_suffix = input("  Tag on ORIGINAL TIFF names (e.g. _orig): ").strip()
    jpeg_suffix = input("  Tag on DERIVATIVE JPEG names: ").strip()

    sets = {
        "Modified TIFF": collect("Modified TIFF", mod_folder, TIF_EXTENSIONS, mod_suffix),
        "Original TIFF": collect("Original TIFF", orig_folder, TIF_EXTENSIONS, orig_suffix),
        "Derivative JPEG": collect("Derivative JPEG", jpeg_folder, JPEG_EXTENSIONS, jpeg_suffix),
    }
    files = {label: found for label, (found, _) in sets.items()}
    problems = [message for _, (_, found_problems) in sets.items() for message in found_problems]

    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        print("The spreadsheet has no data rows. Nothing to do.")
        return
    headings, data_rows = rows[0], rows[1:]
    tags = [mapping.get(h.strip().lower()) or dublin_core_tag(h) for h in headings]
    for index, tag in enumerate(tags[1:], start=1):
        if tag is None:
            problems.append(
                f"Column {index + 1} '{headings[index]}' isn't in the mapping sheet "
                "(this column will be left out of every XML file)"
            )

    sheet = {}  # item name -> (sheet row number, row values)
    for row_number, row in enumerate(data_rows, start=2):
        if not any(cell.strip() for cell in row):
            continue
        name = row[0].strip() if row else ""
        if not name:
            problems.append(f"Spreadsheet row {row_number}: column A is empty")
        elif name in sheet:
            problems.append(
                f"Spreadsheet row {row_number}: '{name}' repeats row {sheet[name][0]} (skipped)"
            )
        else:
            sheet[name] = (row_number, row)

    all_names = set(sheet).union(*files.values())
    ready = []
    for name in sorted(all_names):
        missing = [label for label in files if name not in files[label]]
        if name not in sheet:
            missing.append("spreadsheet row")
        if missing:
            hint = near_miss(name, all_names)
            problems.append(f"'{name}' has no: {', '.join(missing)}{hint}")
            continue
        target = out_folder / name
        if target.exists():
            problems.append(f"'{name}': a folder with that name already exists (skipped)")
            continue
        moving = [files[label][name] for label in files]
        clashes = {f.name.lower() for f in moving}
        if len(clashes) < 3 or f"{name}.xml".lower() in clashes:
            problems.append(
                f"'{name}': two of its files would have the same name inside one folder (skipped)"
            )
            continue
        ready.append(name)

    if mapping_notes:
        print("\nNotes about the mapping sheet:")
        for note in mapping_notes:
            print("  -", note)

    print(
        f"\nFound {len(files['Modified TIFF'])} modified TIFFs, "
        f"{len(files['Original TIFF'])} original TIFFs, "
        f"{len(files['Derivative JPEG'])} derivative JPEGs, "
        f"and {len(sheet)} spreadsheet rows."
    )
    print(f"{len(ready)} items are complete and ready.")
    if problems:
        print(f"\n*** {len(problems)} PROBLEM(S) FOUND ***")
        for message in problems:
            print("  -", message)
        print("\nItems with problems will be left alone (files stay where they are).")

    if not ready:
        print("\nNothing to do.")
        return
    answer = input(f"\nCreate {len(ready)} folders, move the files and write the XML? Type yes to continue: ")
    if answer.strip().lower() != "yes":
        print("Okay, nothing was changed.")
        return

    done = 0
    for name in ready:
        try:
            target = out_folder / name
            target.mkdir()
            for label in files:
                source = files[label][name]
                shutil.move(str(source), str(target / source.name))
            build_xml(tags, sheet[name][1]).write(
                target / f"{name}.xml", encoding="utf-8", xml_declaration=True
            )
            done += 1
        except OSError as error:
            print(f"  Could not finish '{name}': {error}")

    print(f"\nDone. {done} item folders created, each with 3 image files and an XML file.")
    if problems:
        print("Remember to look at the problems listed above.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Nothing further was changed.")
        sys.exit(1)
