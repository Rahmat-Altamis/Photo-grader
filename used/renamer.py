import csv
from pathlib import Path
from config import EDITS, THEMES


def plan_new_name(path: Path, base: str, taken: set) -> Path:
    """Next free name like '1-m-+_001.jpg' (never overwrites anything)."""
    n = 1
    while True:
        candidate = path.with_name(f"{base}_{n:03d}{path.suffix.lower()}")
        if candidate not in taken and not candidate.exists():
            taken.add(candidate)
            return candidate
        n += 1


def apply_renames(rows: list[dict]) -> None:
    for r in rows:
        try:
            r["original"].rename(r["new"])
            r["applied"] = "yes"
        except OSError as e:
            print(f"could not rename {r['original'].name}: {e}")


def write_log(rows: list[dict], log_file: str) -> None:
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["original_path", "new_path", "applied", "use", "post", "sell", "compete",
                    "theme", "edit", "edit_note", "reason"])
        for r in rows:
            w.writerow([r["original"], r["new"], r["applied"], r["use"], r["post"], r["sell"],
                        r["compete"], THEMES[r["theme"]], EDITS[r["edit"]],
                        r["edit_note"], r["reason"]])


def undo(log_file: str) -> int:
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
    return restored