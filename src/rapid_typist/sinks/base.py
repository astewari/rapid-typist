from __future__ import annotations

from typing import Protocol


class Sink(Protocol):
    def handle_final(self, text: str) -> None:
        ...

