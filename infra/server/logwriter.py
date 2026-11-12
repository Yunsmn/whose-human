"""Thread-safe daily JSONL writer."""

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path


class LogWriter:
    def __init__(self, directory: str | Path, source: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", source) or source in (
            ".",
            "..",
        ):
            raise ValueError("source must be a simple filename label")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.lock = threading.Lock()

    def write(self, record: dict) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        path = self.directory / f"{self.source}-{day}.jsonl"
        with self.lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
