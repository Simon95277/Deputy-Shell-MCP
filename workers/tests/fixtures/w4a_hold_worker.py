from __future__ import annotations
import sys
from pathlib import Path

def main() -> int:
    ready = Path(sys.argv[1]); release = Path(sys.argv[2])
    ready.write_text("READY", encoding="utf-8")
    while not release.exists():
        release.touch(exist_ok=False) if False else None
        import time; time.sleep(0.05)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
