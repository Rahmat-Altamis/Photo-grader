import base64
import csv
import io
import json
import re
import time
from pathlib import Path
import requests
from PIL import Image, ImageOps

API_URL = "https://ai.hackclub.com/proxy/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"
JUDGE_MODEL = "z-ai/glm-5.3-flash"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_SIDE = 1920

USES = {
    "1": "worth posting to social media",
    "2": "worth selling",
    "3": "worth entering in a competition",
    "0": "NOT worth any of the three (every score is under its bar)",
}

WORTH_BARS = {"1": 6, "2": 7, "3": 8}

THEMES = {
    "a": ("abstract", "deliberate abstract art / graphics ONLY; never for blurry or unclear photos"),
    "b": ("product", "products, objects, still life"),
    "c": ("city", "buildings / architecture / streets where the PLACE is the subject"),
    "f": ("food", "food and drinks"),
    "l": ("landscape", "scenery, sky, roads, outdoor views with no main person or vehicle"),
    "m": ("vehicle", "cars, motorcycles, racing, panning shots of moving vehicles (even if blurry)"),
    "n": ("nature", "plants, flowers, trees"),
    "p": ("people", "portraits, groups, candid photos of people"),
    "s": ("sport", "sports and action (non-motor)"),
    "w": ("animal", "wildlife, pets, animals"),
    "x": ("other", "screenshots, documents, or anything that fits nothing else"),
}

EDITS = {
    "+": ("exposure", "fix exposure / brightness"),
    "~": ("color", "fix colour / white balance"),
    "#": ("sharpen", "sharpen / reduce noise"),
    "^": ("crop", "crop / straighten / recompose"),
    "@": ("retouch", "remove distractions / retouch"),
    "!": ("reshoot", "major problems, reshoot if possible"),
    "=": ("none", "no edit needed"),
    "%": ("unclear", "edit advice unclear (the AI gave no usable answer)"),
}

KEY2THEME = {key: letter for letter, (key, _) in THEMES.items()}
KEY2EDIT = {key: sym for sym, (key, _) in EDITS.items()}
ALREADY_NAMED = re.compile(r"^[0-3]-[a-z]-[+~#^@!=%]_\d+$")

EDIT_HINTS = [
    (r"crop|rotat|straighten|tilt|orient|frame|compos", "^"),
    (r"exposur|bright|underexpos|overexpos|shadows|highlights", "+"),
    (r"white balance|colou?r|\bcast\b|saturat|tint", "~"),
    (r"sharpen|noise|grain|soft", "#"),
    (r"retouch|distract|clone|erase|remove", "@"),
    (r"reshoot|retake|unusable", "!"),
]

THEME_HINTS = (("car", "m"), ("motor", "m"), ("racing", "m"), ("architect", "c"), ("building", "c"), ("portrait", "p"), ("person", "p"), ("scenery", "l"))

LOG_COLUMNS = ["original_path", "new_path", "applied", "use", "post", "sell", "compete", "theme", "edit", "edit_note", "strength", "reason", "agreement", "correction", "first_post", "first_sell", "first_compete", "first_theme", "judge_error"]

JSON_SHAPE = """Reply with ONLY a JSON object, no markdown, in exactly this shape: {"post": <1-10>, "sell": <1-10>, "compete": <1-10>, "theme": "<theme key>", "edit": "<edit key>", "edit_note": "<specific advice for that edit; empty if edit is none>", "strength": "<the best thing about this image>", "reason": "<one short sentence>"%s}"""


def legend_text() -> str:
    lines = ["Filename = number-letter-symbol_counter, e.g. 1-m-+_001.jpg", "", "NUMBER (best use)"]
    lines += [f"  {k}  {v}" + (f"   (bar: score >= {WORTH_BARS[k]})" if k in WORTH_BARS else "") for k, v in USES.items()]
    lines += ["", "LETTER (theme)"] + [f"  {k}  {key}: {d}" for k, (key, d) in THEMES.items()]
    lines += ["", "SYMBOL (edit to make next)"] + [f"  {k}  {d}" for k, (_, d) in EDITS.items()]
    return "\n".join(lines)


def rubric() -> str:
    themes = "\n".join(f'  "{key}" - {desc}' for key, desc in THEMES.values())
    edits = "\n".join(f'  "{key}" - {desc}' for key, desc in EDITS.values() if key != "unclear")
    return f"""Score each from 1–10. Calibration: 5 = average, 6–7 = good, 8 = strong, 9–10 = rare. Be fair, noting strengths and only visible flaws.
- post: Social media impact, eye-catching appeal, shareability.
- sell: Commercial value for stock, prints, or clients. Private screenshots/documents score 1.
- compete: Photo contest potential, considering originality, technical quality, composition, and storytelling.
Theme: Return ONE key from:
{themes}
Edit: Return ONE key for the most valuable fix, or "none" if no fix is needed:
{edits}
The image is already upright. Suggest rotation only if the horizon or verticals are visibly tilted."""


def build_prompt() -> str:
    return "You are a professional photo editor and curator. Evaluate the attached image.\n\n" + rubric() + "\n\n" + JSON_SHAPE % ""


def build_judge_prompt(first: dict) -> str:
    review = json.dumps({k: first[k] for k in ("post", "sell", "compete", "theme", "edit", "edit_note", "strength", "reason")}, ensure_ascii=False)
    return ("You are the senior judge of a photo contest. A first reviewer evaluated the attached image and produced the review below. First reviewers often make mistakes: they invent flaws that are not there (for example calling an upright image sideways), choose the wrong theme, and are too harsh or too generous. Do NOT anchor on their numbers. Look at the image yourself, check every claim against what you actually see, then give your own FINAL verdict.\n\n"
            f"FIRST REVIEWER'S REVIEW:\n{review}\n\n" + rubric() + "\n\n" + JSON_SHAPE % ',\n "correction": "<what the first reviewer got wrong, or empty if nothing>"')


def find_images(folder: Path, recursive: bool = False, skip_named: bool = True) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pattern) if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not (skip_named and ALREADY_NAMED.match(p.stem)))


def encode_image(path: Path, max_side: int = MAX_SIDE) -> str:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    decoder, found = json.JSONDecoder(), None
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and "post" in obj:
            found = obj
    if found is None:
        raise ValueError(f"no usable JSON in reply: {text[:120]!r}")
    return found


def parse_score(data: dict, key: str) -> int:
    if key not in data:
        raise ValueError(f"reply is missing '{key}'")
    return int(max(1, min(10, round(float(data[key])))))


def parse_theme(raw) -> str:
    raw = str(raw or "").strip().lower()
    if raw in THEMES:
        return raw
    if raw in KEY2THEME:
        return KEY2THEME[raw]
    for key, letter in KEY2THEME.items():
        if key in raw:
            return letter
    for word, letter in THEME_HINTS:
        if word in raw:
            return letter
    return "x"


def parse_edit(raw, note: str) -> str:
    raw = str(raw or "").strip().lower()
    if raw in EDITS and raw != "%":
        return raw
    if raw in KEY2EDIT and raw != "unclear":
        return KEY2EDIT[raw]
    if raw.startswith("no"):
        return "="
    for key, sym in KEY2EDIT.items():
        if key != "unclear" and key in raw:
            return sym
    for pattern, sym in EDIT_HINTS:
        if re.search(pattern, note.lower()):
            return sym
    return "%"


def parse_reply(text: str) -> dict:
    d = extract_json(text)
    note = str(d.get("edit_note", "") or "").strip()
    return {
        "post": parse_score(d, "post"), "sell": parse_score(d, "sell"), "compete": parse_score(d, "compete"),
        "theme": parse_theme(d.get("theme")), "edit": parse_edit(d.get("edit"), note), "edit_note": note,
        "strength": str(d.get("strength", "") or "").strip(),
        "reason": str(d.get("reason", "") or "").strip(),
        "correction": str(d.get("correction", "") or "").strip(),
    }


def chat(model: str, api_key: str, prompt: str, data_url: str, timeout: int = 180) -> str:
    payload = {"model": model, "temperature": 0.2, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]}]}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last = ""
    for attempt in range(4):
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 429 or resp.status_code >= 500:
            last = f"HTTP {resp.status_code}"
            time.sleep(2 * (2 ** attempt))
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"{model}: HTTP {resp.status_code} {resp.text[:200]}")
        content = resp.json()["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError(f"{model}: empty reply")
        return content
    raise RuntimeError(f"{model}: gave up after retries ({last})")


def agreement(first: dict, final: dict) -> str:
    gap = max(abs(first[k] - final[k]) for k in ("post", "sell", "compete"))
    if first["theme"] != final["theme"] or gap >= 3:
        return "overruled"
    return "adjusted" if gap == 2 else "agree"


def evaluate(path: Path, api_key: str, grader_model: str = DEFAULT_MODEL, judge_model: str | None = None, max_side: int = MAX_SIDE) -> dict:
    data_url = encode_image(path, max_side)
    first = parse_reply(chat(grader_model, api_key, build_prompt(), data_url))
    if not judge_model:
        return {**first, "first": None, "agreement": "-", "judge_error": ""}
    try:
        final = parse_reply(chat(judge_model, api_key, build_judge_prompt(first), data_url))
    except Exception as e:
        return {**first, "first": None, "agreement": "judge failed", "judge_error": str(e)}
    return {**final, "first": first, "agreement": agreement(first, final), "judge_error": ""}


def best_use(grades: dict, bars: dict | None = None) -> str:
    bars = bars or WORTH_BARS
    scores = {"1": grades["post"], "2": grades["sell"], "3": grades["compete"]}
    passing = [k for k in scores if scores[k] >= bars[k]]
    return max(passing, key=lambda k: scores[k]) if passing else "0"


def base_name(use: str, grades: dict) -> str:
    return f"{use}-{grades['theme']}-{grades['edit']}"


def plan_new_name(path: Path, base: str, taken: set) -> Path:
    n = 1
    while True:
        cand = path.with_name(f"{base}_{n:03d}{path.suffix.lower()}")
        if cand not in taken and (cand == path or not cand.exists()):
            taken.add(cand)
            return cand
        n += 1


def apply_renames(rows: list[dict]) -> None:
    for r in rows:
        try:
            if r["original"] != r["new"]:
                r["original"].rename(r["new"])
            r["applied"] = "yes"
        except OSError as e:
            print(f"could not rename {r['original'].name}: {e}")


def write_log(rows: list[dict], log_file) -> None:
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LOG_COLUMNS)
        for r in rows:
            f1 = r.get("first") or {}
            w.writerow([
                r["original"], r["new"], r["applied"], r["use"], r["post"], r["sell"], r["compete"],
                THEMES[r["theme"]][0], EDITS[r["edit"]][1], r["edit_note"], r.get("strength", ""),
                r["reason"], r.get("agreement", "-"), r.get("correction", ""),
                f1.get("post", ""), f1.get("sell", ""), f1.get("compete", ""),
                THEMES[f1["theme"]][0] if f1 else "", r.get("judge_error", ""),
            ])


def undo(log_file) -> int:
    restored = 0
    with open(log_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["applied"] != "yes":
                continue
            old, new = Path(row["original_path"]), Path(row["new_path"])
            if new.exists() and not old.exists() and old != new:
                new.rename(old)
                restored += 1
    return restored