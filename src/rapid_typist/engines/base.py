from __future__ import annotations

from typing import Protocol
import numpy as np


class Transcriber(Protocol):
    def transcribe(self, pcm: np.ndarray) -> str:  # returns final text
        ...
