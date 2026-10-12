import json
import re
import time
from pathlib import Path
import requests
from config import API_URL, EDITS, THEMES
from imaging import encode_image
from prompt import build_prompt
 
def _clamp_score(value) -> int:
    return int(max(1, min(10, round(float(value)))))
 
 
def parse_reply(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in reply: {text[:100]!r}")
    data = json.loads(match.group(0))
 
    theme = str(data.get("theme", "x")).strip().lower()[:1]

    edit = str(data.get("edit", "=")).strip()[:1]
    return {
        "post": _clamp_score(data["post"]),
        "sell": _clamp_score(data["sell"]),
        "compete": _clamp_score(data["compete"]),
        "theme": theme if theme in THEMES else "x",
        "edit": edit if edit in EDITS else "=",
        "edit_note": str(data.get("edit_note", "")).strip(),
        "reason": str(data.get("reason", "")).strip(),
    }

def rate_image(path: Path, api_key: str, model: str, max_side: int = 1024) -> dict:
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
