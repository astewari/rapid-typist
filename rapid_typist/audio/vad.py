from __future__ import annotations

from collections import deque
from typing import Deque, Iterator, Tuple

import numpy as np
import webrtcvad


class Segmenter:
    def __init__(
        self,
        aggressiveness: int = 2,
        frame_ms: int = 30,
        hangover_ms: int = 300,
        preroll_ms: int = 150,
        samplerate: int = 16000,
    ) -> None:
        assert frame_ms in (10, 20, 30)
        self.vad = webrtcvad.Vad(aggressiveness)
        self.frame_ms = frame_ms
        self.hangover_frames = max(1, hangover_ms // frame_ms)
        self.preroll_frames = max(0, preroll_ms // frame_ms)
        self.samplerate = samplerate

    def _frame_bytes(self, pcm: np.ndarray) -> bytes:
        return pcm.tobytes()

    def run(self, frames: Iterator[np.ndarray]) -> Iterator[Tuple[np.ndarray, bool, float]]:
        """Yield (frame, is_speech, level_dbfs) for each 30ms frame.
        Also internally detects segments and yields final segments through a side-channel? Not here.
        This generator is used by the higher-level pipeline to build segments.
        """
        from .utils import rms_dbfs

        for pcm in frames:
            is_speech = False
            try:
                is_speech = self.vad.is_speech(self._frame_bytes(pcm), self.samplerate)
            except Exception:
                is_speech = False
            level = rms_dbfs(pcm)
            yield pcm, is_speech, level

    def segments(self, frames: Iterator[np.ndarray]) -> Iterator[np.ndarray]:
        """Build segments from frames using VAD with hangover and preroll."""
        active: bool = False
        hang: int = 0
        pre: Deque[np.ndarray] = deque(maxlen=self.preroll_frames)
        cur: Deque[np.ndarray] = deque()
        for pcm, speech, _ in self.run(frames):
            if speech:
                hang = self.hangover_frames
                if not active:
                    active = True
                    # start segment with preroll
                    cur.extend(list(pre))
                cur.append(pcm)
            else:
                if active:
                    if hang > 0:
                        hang -= 1
                        cur.append(pcm)
                    else:
                        # finalize
                        seg = np.concatenate(list(cur)) if len(cur) else np.zeros(0, dtype=np.int16)
                        if seg.size:
                            yield seg
                        cur.clear()
                        active = False
                        pre.clear()
                else:
                    pre.append(pcm)

    def monitor(self, frames: Iterator[np.ndarray]):
        """Yield tuples (segment or None, vad_active: bool, level_dbfs: float).
        Allows UI to update on every frame while emitting segments when finalized.
        """
        active: bool = False
        hang: int = 0
        pre: Deque[np.ndarray] = deque(maxlen=self.preroll_frames)
        cur: Deque[np.ndarray] = deque()
        for pcm, speech, level in self.run(frames):
            seg_out = None
            if speech:
                hang = self.hangover_frames
                if not active:
                    active = True
                    cur.extend(list(pre))
                cur.append(pcm)
            else:
                if active:
                    if hang > 0:
                        hang -= 1
                        cur.append(pcm)
                    else:
                        seg = np.concatenate(list(cur)) if len(cur) else np.zeros(0, dtype=np.int16)
                        if seg.size:
                            seg_out = seg
                        cur.clear()
                        active = False
                        pre.clear()
                else:
                    pre.append(pcm)
            yield seg_out, active, level

