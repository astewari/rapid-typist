from __future__ import annotations

import subprocess

from .base import Sink


class PasteSink(Sink):
    def handle_final(self, text: str) -> None:
        # Put text on clipboard, then synthesize Cmd+V
        p = subprocess.Popen(["/usr/bin/pbcopy"], stdin=subprocess.PIPE)
        if p.stdin:
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
        p.wait(timeout=2)

        osa = 'tell application "System Events" to keystroke "v" using command down'
        subprocess.run(["/usr/bin/osascript", "-e", osa], check=False)


