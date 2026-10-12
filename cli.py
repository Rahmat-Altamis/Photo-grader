import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import core

def main():
    ap = argparse.ArgumentParser(description="Grade, classify and rename images with Hack Club AI.")
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--apply", action="store_true", help="really rename (default: preview only)")
    ap.add_argument("--undo", metavar="LOG.csv", help="restore names from a log")
    ap.add_argument("--model", default=core.DEFAULT_MODEL, help="first-pass grader model")
    ap.add_argument("--judge", default=core.JUDGE_MODEL, help="judge model (final grades)")
    ap.add_argument("--no-judge", action="store_true", help="skip the judge")
    ap.add_argument("--bars", default="6,7,8", help="worth bars for post,sell,compete (default 6,7,8)")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--include-renamed", action="store_true", help="also re-rate files already renamed")
    ap.add_argument("--max-side", type=int, default=core.MAX_SIDE, help="longest side sent to the AI in px (default 1920)")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    if args.undo:
        print(f"Restored {core.undo(args.undo)} file(s).")
        return

    try:
        bars = dict(zip("123", (int(x) for x in args.bars.split(","))))
        assert len(bars) == 3
    except (ValueError, AssertionError):
        sys.exit("--bars needs three numbers, e.g. --bars 6,7,8")

    key = os.environ.get("HACKCLUB_API_KEY")
    if not key:
        sys.exit("Set HACKCLUB_API_KEY first (key from https://ai.hackclub.com).")
    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"'{folder}' is not a folder.")
    images = core.find_images(folder, args.recursive, skip_named=not args.include_renamed)
    if not images:
        sys.exit("No images found (already-renamed files are skipped unless --include-renamed).")

    judge = None if args.no_judge else args.judge
    print(f"{len(images)} image(s) | grader {args.model} | judge {judge or 'off'} | "
          f"{'RENAMING' if args.apply else 'PREVIEW (add --apply)'}\n")
    rows, taken = [], set()
    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {path.name}")
        try:
            g = core.evaluate(path, key, args.model, judge, args.max_side)
        except Exception as e:
            print(f"    !! failed: {e}")
            continue
        g["use"] = core.best_use(g, bars)
        g.update(original=path, new=core.plan_new_name(path, core.base_name(g["use"], g), taken),
                 applied="no")
        print(f"    post {g['post']} | sell {g['sell']} | compete {g['compete']}  "
              f"[{g['agreement']}]  ->  {g['new'].name}")
        if g["correction"]:
            print(f"    judge: {g['correction']}")
        if g["judge_error"]:
            print(f"    judge error: {g['judge_error']}")
        rows.append(g)
        time.sleep(args.delay)

    if not rows:
        sys.exit("Nothing was rated.")
    if args.apply:
        core.apply_renames(rows)
    log = f"ratings_{datetime.now():%Y%m%d_%H%M%S}.csv"
    core.write_log(rows, log)
    print(f"\nLog saved to {log}")


if __name__ == "__main__":
    main()