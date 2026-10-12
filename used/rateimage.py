import argparse
import base64
import csv
import io
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    from PIL import Image
except ImportError:
    Image = None

API_URL = "https://ai.hackclub.com/proxy/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"  # must be a vision-capable model
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

USES = {
    "1": "worth posting to social media",
    "2": "worth selling",
    "3": "worth entering in a competition",
    "0": "not ready for any of the three",
}

THEMES = {
    "a": "abstract / art / graphic",
    "b": "business / product",
    "c": "city / architecture",
    "f": "food / drink",
    "l": "landscape / scenery",
    "m": "motorsport / vehicles",
    "n": "nature / plants / flowers",
    "p": "people / portrait",
    "s": "sports / action (non-motor)",
    "w": "wildlife / animals / pets",
    "x": "other / unclear",
}

EDITS = {
    "+": "fix exposure / brightness",
    "~": "fix colour / white balance / colour grade",
    "#": "sharpen / reduce noise",
    "^": "crop / straighten / recompose",
    "@": "retouch / remove distractions",
    "!": "major problems, reshoot if possible",
    "=": "no edit needed",
}
ALREADY_NAMED = re.compile(r"^[0-3]-[a-z]-[+~#^@!=]_\d+$")

def build_prompt() -> str:
    themes = "\n".join(f'  "{k}" = {v}' for k, v in THEMES.items())
    edits = "\n".join(f'  "{k}" = {v}' for k, v in EDITS.items())
    return f"""You are a professional photo editor and curator. Evaluate the attached image three ways. Score each from 1 to 10 (be honest, 5 is average, 9-10 is rare): post: how well it would do on social media (instant impact, eye-catching, shareable) sell: commercial value for stock / prints / clients (technical quality, clean, marketable subject, no distracting logos or people who'd need a release) compete: how it would do in a photo contest (originality, technical excellence, storytelling, strong composition) then choose ONE theme letter: {themes} And ONE edit symbol, the single most valuable improvement to make next: {edits} Reply with ONLY a JSON object, no markdown, in exactly this shape: {{"post": <1-10>, "sell": <1-10>, "compete": <1-10>, "theme": "<letter>", "edit": "<symbol>", "edit_note": "<short, specific edit advice>", "reason": "<one short sentence>"}}"""

def encode_image(path: Path, max_side: int) -> str:
    if Image is not None:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()

def clamp_score(value) -> int:
    return int(max(1, min(10, round(float(value)))))

def parse_reply(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in reply: {text[:100]!r}")
    data = json.loads(match.group(0))

    theme = str(data.get("theme", "x")).strip().lower()[:1]
    edit = str(data.get("edit", "=")).strip()[:1]
    return {
        "post": clamp_score(data["post"]),
        "sell": clamp_score(data["sell"]),
        "compete": clamp_score(data["compete"]),
        "theme": theme if theme in THEMES else "x",
        "edit": edit if edit in EDITS else "=",
        "edit_note": str(data.get("edit_note", "")).strip(),
        "reason": str(data.get("reason", "")).strip(),
    }

def rate_image(path: Path, api_key: str, model: str, max_side: int) -> dict:
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_prompt()},
                    {"type": "image_url", "image_url": {"url": encode_image(path, max_side)}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(4):
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2 * (2 ** attempt)
            print(f"    (server said {resp.status_code}, retrying in {wait}s)")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return parse_reply(resp.json()["choices"][0]["message"]["content"])

    raise RuntimeError("too many failed attempts")

def best_use(r: dict, min_score: int) -> str:
    scores = {"1": r["post"], "2": r["sell"], "3": r["compete"]}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= min_score else "0"

def find_images(folder: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [
        p for p in folder.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not ALREADY_NAMED.match(p.stem)
    ]
    return sorted(files)

def plan_new_name(path: Path, base: str, taken: set) -> Path:
    n = 1
    while True:
        candidate = path.with_name(f"{base}_{n:03d}{path.suffix.lower()}")
        if candidate not in taken and not candidate.exists():
            taken.add(candidate)
            return candidate
        n += 1

def undo(log_file: str):
    restored = 0
    with open(log_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["applied"] != "yes":
                continue
            old, new = Path(row["original_path"]), Path(row["new_path"])
            if new.exists() and not old.exists():
                new.rename(old)
                restored += 1
                print(f"restored {new.name} -> {old.name}")
    print(f"\nRestored {restored} file(s).")
def main():
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
    args = ap.parse_args()

    if args.undo:
        undo(args.undo)
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
            r = rate_image(path, api_key, args.model, args.max_side)
        except Exception as e: 
            print(f"    !! failed: {e}")
            continue

        use = best_use(r, args.min_score)
        base = f"{use}-{r['theme']}-{r['edit']}"
        new_path = plan_new_name(path, base, taken)
        r.update(use=use, original=path, new=new_path, applied="no")

        print(f"    post {r['post']} | sell {r['sell']} | compete {r['compete']}"
              f"  ->  {new_path.name}")
        print(f"    {THEMES[r['theme']]} | edit: {EDITS[r['edit']]}"
              + (f" ({r['edit_note']})" if r["edit_note"] else ""))
        rows.append(r)
        time.sleep(args.delay)

    if not rows:
        sys.exit("\nNothing was rated successfully.")

    if args.apply:
        for r in rows:
            try:
                r["original"].rename(r["new"])
                r["applied"] = "yes"
            except OSError as e:
                print(f"could not rename {r['original'].name}: {e}")

    log = args.log or f"ratings_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(log, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["original_path", "new_path", "applied", "use", "post", "sell", "compete",
                    "theme", "edit", "edit_note", "reason"])
        for r in rows:
            w.writerow([r["original"], r["new"], r["applied"], r["use"], r["post"], r["sell"],
                        r["compete"], THEMES[r["theme"]], EDITS[r["edit"]], r["edit_note"], r["reason"]])

    print("\n=== Summary ===")
    for code, label in USES.items():
        count = sum(1 for r in rows if r["use"] == code)
        if count:
            print(f"  {code} {label}: {count}")
    done = sum(1 for r in rows if r["applied"] == "yes")
    print(f"\nLog saved to {log}" + (f" ({done} renamed; undo with --undo {log})" if args.apply else ""))

if __name__ == "__main__":
    main()