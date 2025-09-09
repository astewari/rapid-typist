from __future__ import annotations

import numpy as np

from .base import Transcriber
from ..audio.utils import int16_to_float32


class WhisperCppTranscriber(Transcriber):
    def __init__(self, model_name: str = "base.en", language: str = "en") -> None:
        try:
            from pywhispercpp.model import Model  # type: ignore
        except Exception as e:  # pragma: no cover
            raise ImportError(
                "pywhispercpp is not available. Please install on Python 3.11+."
            ) from e
        self.Model = Model
        self.language = language
        # Load model; pywhispercpp caches under ~/Library/Application Support/pywhispercpp/models
        self.model = self.Model(model_name)
        # Emit info; pywhispercpp prints Metal/CoreML usage to stdout when initializing
        try:
            info = self.model.system_info()
            print(f"[rapid-typist] whisper.cpp ready — system_info: {info}")
        except Exception:
            print(f"[rapid-typist] whisper.cpp ready (model={model_name})")

    def transcribe(self, pcm: np.ndarray) -> str:
        audio = int16_to_float32(pcm)
        segs = self.model.transcribe(audio, language=self.language)
        try:
            return " ".join(getattr(s, "text", str(s)) for s in segs).strip()
        except Exception:
            return ""
