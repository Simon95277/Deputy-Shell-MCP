from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path

def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, sort_keys=True, indent=2)
            f.write("\n")
            f.flush(); os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(name, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in {5, 32} or attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        if os.path.exists(name): os.unlink(name)

def read_json(path: Path) -> dict:
    last = None
    for attempt in range(4):
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, PermissionError) as exc:
            last = exc
            if attempt == 3:
                raise
            time.sleep(0.01 * (attempt + 1))
    raise last
