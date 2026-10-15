"""Stage-by-stage persistent cache, hashed over all inputs affecting results."""
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import tempfile


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Cache:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def get(self, key: str) -> dict | None:
        target = self.directory / f"{key}.json"
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8"))
        return None

    def put(self, key: str, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{key}.json"
        fd, temp = tempfile.mkstemp(dir=self.directory, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
