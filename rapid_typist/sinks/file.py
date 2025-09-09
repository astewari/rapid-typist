from __future__ import annotations

from pathlib import Path
from .base import Sink


class FileSink(Sink):
    def __init__(self, directory: str, separator: str = "\n") -> None:
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.separator = separator
        self.file = self.dir / "rapid-typist.txt"

    def handle_final(self, text: str) -> None:
        with self.file.open("a", encoding="utf-8") as f:
            f.write(text)
            f.write(self.separator)


