import re

API_URL = "https://ai.hackclub.com/proxy/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"
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