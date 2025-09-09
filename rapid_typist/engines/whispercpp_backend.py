from __future__ import annotations

import numpy as np

from .base import Transcriber
from ..audio.utils import int16_to_float32


class WhisperCppTranscriber(Transcriber):
    def __init__(self, model_name: str = "base.en", language: str = "en") -> None:
        try:
            from whispercpp import Whisper  # type: ignore
        except Exception as e:  # pragma: no cover
            raise ImportError(
                "whispercpp is not available. It requires Python >=3.10 wheels or a local build with Metal/CoreML."
            ) from e
        self.Whisper = Whisper
        self.language = language
        # Load default model (will download/cache to ~/.cache/whispercpp by default)
        self.model = self.Whisper.from_pretrained(model_name)
        # Log engine init; whisper.cpp uses Metal/CoreML if compiled that way
        print(f"[rapid-typist] Whisper.cpp model '{model_name}' initialized (backend auto: CPU/Metal/CoreML depending on build)")

    def transcribe(self, pcm: np.ndarray) -> str:
        audio = int16_to_float32(pcm)
        # whispercpp expects float32 PCM [-1,1]
        out = self.model.transcribe(audio)
        # transcribe may return a generator/iterable of segments; join if needed
        if isinstance(out, str):
            return out.strip()
        try:
            return " ".join(seg.text if hasattr(seg, "text") else str(seg) for seg in out).strip()
        except Exception:
            return ""

