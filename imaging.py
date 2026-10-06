
import base64
import io
import mimetypes
from pathlib import Path
from config import ALREADY_NAMED, IMAGE_EXTS
 
try:
    from PIL import Image
except ImportError:
    Image = None

def find_images(folder: Path, recursive: bool = False) -> list[Path]:
    """Image files in a folder, skipping ones this tool already renamed."""
    pattern = "**/*" if recursive else "*"
    files = [
        p for p in folder.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not ALREADY_NAMED.match(p.stem)
    ]
    return sorted(files)

def encode_image(path: Path, max_side: int = 1024) -> str:
    if Image is not None:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
 
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()