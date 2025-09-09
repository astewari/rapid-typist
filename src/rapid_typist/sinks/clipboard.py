from __future__ import annotations

import subprocess

from .base import Sink


class ClipboardSink(Sink):
    def handle_final(self, text: str) -> None:
        p = subprocess.Popen(["/usr/bin/pbcopy"], stdin=subprocess.PIPE)
        if p.stdin:
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
        p.wait(timeout=2)

