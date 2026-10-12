import argparse
import sys
import time
import sys
from datetime import datetime
from pathlib import Path
from client import rate_image
from config import DEFAULT_MODEL, EDITS, THEMES, USES
from grading import base_name, best_use
from imaging import find_images
from renamer import appy_renames, plan_new_name, undo, write_log

def parse_args():
    ap = argparse.ArgumentParser(description="Grade, classify and rename images with Hack Club AI.")
    ap.add_argument("folder", nargs="?", default=".", help="folder with images (default: current)")
    ap.add_argument("--apply", action="store_true", help="really rename the files (default: preview only)")
    ap.add_argument("--undo", metavar="LOG.csv", help="restore names from a previous run's log")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--recursive", action="store_true", help="include subfolders")
    ap.add_argument("--min-score", type=int, default=4, help="best score below this -> number 0 (default 4)")
    ap.add_argument("--max-side", type=int, default=1024, help="resize longest side before upload (needs Pillow)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--log", default=None, help="CSV log path (default: ratings_<timestamp>.csv)")
    return ap.parse_args()

def main():
    args = parse_args()
 
    if args.undo:
        print(f"\nRestored {undo(args.undo)} file(s).")
        return

    api_key = os.environ.get("HACKCLUB_API_KEY")
    if not api_key:
        sys.exit("Set HACKCLUB_API_KEY first (get a key at https://ai.hackclub.com).")

    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"'{folder}' is not a folder.")
 
    images = find_images(folder, args.recursive)
    if not images:
        sys.exit(f"No new images found in '{folder}' (already-renamed files are skipped).")
 
    mode = "RENAMING" if args.apply else "PREVIEW (add --apply to rename)"
    print(f"{len(images)} image(s) | model {args.model} | {mode}\n")

    rows, taken = [], set()
    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {path.name}")
        try:
            grades = rate_image(path, api_key, args.model, args.max_side)
        except Exception as e:
            print(f"    !! failed: {e}")
            continue


        use = best_use(grades, args.min_score)
        new_path = plan_new_name(path, base_name(use, grades), taken)
        grades.update(use=use, original=path, new=new_path, applied="no")
 
        print(f"    post {grades['post']} | sell {grades['sell']} | compete {grades['compete']}"
              f"  ->  {new_path.name}")
        note = f" ({grades['edit_note']})" if grades["edit_note"] else ""
        print(f"    {THEMES[grades['theme']]} | edit: {EDITS[grades['edit']]}{note}")
        rows.append(grades)
        time.sleep(args.delay)

    if not rows:
        sys.exit("\nNothing was rated successfully.")
 
    if args.apply:
        apply_renames(rows)
 
    log = args.log or f"ratings_{datetime.now():%Y%m%d_%H%M%S}.csv"
    write_log(rows, log)
 
    print("\n=== Summary ===")
    for code, label in USES.items():
        count = sum(1 for r in rows if r["use"] == code)
        if count:
            print(f"  {code} {label}: {count}")
    done = sum(1 for r in rows if r["applied"] == "yes")
    print(f"\nLog saved to {log}" + (f" ({done} renamed; undo with --undo {log})" if args.apply else ""))
 
if __name__ == "__main__":
    main()
