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
from pathlib import Path
import requests

API_URL = "https://ai.hackclub.com/proxy/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash" 
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

try:
    from PIL import Image
except ImportError:
    Image = None

def build_prompt(criteria: str) -> str:
    return (
        "You are an image critic. Rate the attached image from 1 to 10 "
        f"based on: {criteria}.\n"
        "Be honest and use the full range (5 is average, 9-10 is rare).\n"
        "Reply with ONLY a JSON object, no markdown, in this exact shape:\n"
        '{"score": <number 1-10>, "reason": "<one short sentence>"}'
    )

def encode_image(path: Path, max_side: int) -> str:
    if Image is not None:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
 
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"

def parse_rating(text: str) -> tuple[float, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            score = float(data["score"])
            return max(1.0, min(10.0, score)), str(data.get("reason", "")).strip()
        except (ValueError, KeyError, TypeError):
            pass


    num = re.search(r"\b(10|[1-9])(?:\.\d+)?\b", text)
    if num:
        return float(num.group(0)), text.strip()[:200]
    raise ValueError(f"Couldn't find a score in reply: {text[:100]!r}")


def rate_image(path: Path, api_key: str, model: str, criteria: str, max_side: int):
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_prompt(criteria)},
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
        content = resp.json()["choices"][0]["message"]["content"]
        return parse_rating(content)
 
    raise RuntimeError("Too many failed attempts")

def find_images(folder: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [p for p in folder.glob(pattern) if p.suffix.lower() in IMAGE_EXTS and p.is_file()]
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Rate images in a folder with Hack Club AI.")
    parser.add_argument("folder", nargs="?", default=".", help="folder with images (default: current)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"vision model (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--criteria",
        default="overall quality, composition, lighting and visual appeal",
        help="what the AI should judge the images on",
    )
    parser.add_argument("--recursive", action="store_true", help="include subfolders")
    parser.add_argument("--max-side", type=int, default=1024, help="resize longest side to this (needs Pillow)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds to wait between requests")
    parser.add_argument("--output", default="ratings.csv", help="CSV file to save results to")
    args = parser.parse_args()


    api_key = os.environ.get("HACKCLUB_API_KEY")
    if not api_key:
        sys.exit("Set HACKCLUB_API_KEY first (get a key at https://ai.hackclub.com).")
 
    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"'{folder}' is not a folder.")
 
    images = find_images(folder, args.recursive)
    if not images:
        sys.exit(f"No images found in '{folder}'.")
 
    print(f"Rating {len(images)} image(s) with {args.model}\n")
    results = []

    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {path.name}")
        try:
            score, reason = rate_image(path, api_key, args.model, args.criteria, args.max_side)
            print(f"    -> {score:g}/10  {reason}")
            results.append((path, score, reason))
        except Exception as e:
            print(f"    !! failed: {e}")
        time.sleep(args.delay)
 
    if not results:
        sys.exit("\nNo images were rated successfully.")
 
    results.sort(key=lambda r: r[1], reverse=True)

    print("\n=== Ranking ===")
    for rank, (path, score, reason) in enumerate(results, 1):
        print(f"{rank:>3}. {score:>4g}/10  {path.name}")
 
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "score", "reason"])
        for path, score, reason in results:
            writer.writerow([str(path), score, reason])
    print(f"\nSaved to {args.output}")
 
 
if __name__ == "__main__":
    main()
