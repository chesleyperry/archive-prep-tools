"""Move matching TIF and JPEG files into one new folder per file name.

Run it with:  python3 sort_into_folders.py
It will ask for the two folders and where to put the new folders.
Nothing is moved until you have seen the report and typed "yes".
"""

import shutil
import sys
from pathlib import Path

TIF_EXTENSIONS = {".tif", ".tiff"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}


def ask_for_folder(question):
    """Ask for a folder; dragging a folder into Terminal pastes its path."""
    while True:
        answer = input(question).strip().strip("'\"").replace("\\ ", " ")
        folder = Path(answer).expanduser()
        if folder.is_dir():
            return folder
        print("  That isn't a folder I can find. Please try again.")


def collect(folder, extensions):
    """Return ({name without extension: file}, [problem messages])."""
    found = {}
    problems = []
    for item in sorted(folder.iterdir()):
        if item.name.startswith(".") or not item.is_file():
            continue
        if item.suffix.lower() not in extensions:
            problems.append(f"Unexpected file type in {folder.name}: {item.name}")
            continue
        if item.stem in found:
            problems.append(
                f"Two files with the same name in {folder.name}: "
                f"{found[item.stem].name} and {item.name}"
            )
            continue
        found[item.stem] = item
    return found, problems


def main():
    print("Sort TIF and JPEG files into one folder per file name.\n")
    tif_folder = ask_for_folder("Drag the TIF folder here and press Return: ")
    jpeg_folder = ask_for_folder("Drag the JPEG folder here and press Return: ")
    out_folder = ask_for_folder(
        "Drag the folder where the new folders should be created and press Return: "
    )

    tifs, problems = collect(tif_folder, TIF_EXTENSIONS)
    jpegs, more_problems = collect(jpeg_folder, JPEG_EXTENSIONS)
    problems += more_problems

    matched = sorted(set(tifs) & set(jpegs))
    only_tif = sorted(set(tifs) - set(jpegs))
    only_jpeg = sorted(set(jpegs) - set(tifs))

    for name in only_tif:
        problems.append(f"Has a TIF but no JPEG: {name}")
    for name in only_jpeg:
        problems.append(f"Has a JPEG but no TIF: {name}")
    for name in matched:
        if (out_folder / name).exists():
            problems.append(f"A folder named '{name}' already exists in the destination")

    print(f"\nFound {len(tifs)} TIF files and {len(jpegs)} JPEG files.")
    print(f"{len(matched)} names match in both folders.")

    if problems:
        print(f"\n*** {len(problems)} PROBLEM(S) FOUND ***")
        for message in problems:
            print("  -", message)
        print("\nFiles with problems will be left where they are.")

    ready = [name for name in matched if not (out_folder / name).exists()]
    if not ready:
        print("\nNothing to move.")
        return

    answer = input(f"\nCreate {len(ready)} folders and move the files? Type yes to continue: ")
    if answer.strip().lower() != "yes":
        print("Okay, nothing was moved.")
        return

    moved = 0
    for name in ready:
        try:
            new_folder = out_folder / name
            new_folder.mkdir()
            shutil.move(str(tifs[name]), str(new_folder / tifs[name].name))
            shutil.move(str(jpegs[name]), str(new_folder / jpegs[name].name))
            moved += 1
        except OSError as error:
            print(f"  Could not finish '{name}': {error}")

    print(f"\nDone. {moved} folders created, each with a TIF and a JPEG inside.")
    if problems:
        print("Remember to look at the problems listed above.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Nothing further was moved.")
        sys.exit(1)
