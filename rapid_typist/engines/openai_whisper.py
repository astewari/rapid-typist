from __future__ import annotations

import time
from typing import Optional

import numpy as np
import torch
import whisper  # type: ignore

from .base import Transcriber
from ..audio.utils import int16_to_float32


class WhisperTranscriber(Transcriber):
    def __init__(self, model_name: str = "base.en", language: str = "en") -> None:
        self.model_name = model_name
        self.language = language
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            self.model = whisper.load_model(model_name, device=self.device)
            print(f"[rapid-typist] Whisper model '{model_name}' initialized on device: {self._device_label(self.device)}")
        except Exception as e:
            # Fallback to CPU if MPS initialization fails
            if self.device != "cpu":
                print(f"[rapid-typist] MPS init failed ({e}). Falling back to CPU.")
            self.device = "cpu"
            self.model = whisper.load_model(model_name, device=self.device)
            print(f"[rapid-typist] Whisper model '{model_name}' initialized on device: {self._device_label(self.device)}")

    def transcribe(self, pcm: np.ndarray) -> str:
        audio = int16_to_float32(pcm)
        t0 = time.time()
        # Use Whisper's transcribe with numpy input; disable fp16 on CPU for stability
        result = self.model.transcribe(
            audio=audio,
            language=self.language,
            fp16=False,
            verbose=False,
        )
        _latency = int((time.time() - t0) * 1000)
        text = result.get("text", "").strip()
        return text

    @staticmethod
    def _device_label(device: str) -> str:
        if device == "mps":
            return "GPU/Metal (MPS)"
        if device == "cuda":
            return "GPU/CUDA"
        return "CPU"
