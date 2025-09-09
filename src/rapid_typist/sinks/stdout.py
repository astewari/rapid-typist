from __future__ import annotations

from .base import Sink


class StdoutSink(Sink):
    def handle_final(self, text: str) -> None:
        print(text, flush=True)

