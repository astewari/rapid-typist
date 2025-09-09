from __future__ import annotations

import threading
from queue import Queue
from typing import Iterator, Optional

import numpy as np
import sounddevice as sd


class AudioCapture:
    def __init__(self, samplerate: int = 16000, block_ms: int = 30, device: Optional[str] = None) -> None:
        self.samplerate = samplerate
        self.block = int(samplerate * (block_ms / 1000.0))
        self.device = device
        self._queue: "Queue[np.ndarray]" = Queue(maxsize=100)
        self._stream: Optional[sd.InputStream] = None
        self._running = threading.Event()

    def _callback(self, indata, frames, time, status):
        if status:
            # drop status to avoid blocking audio thread
            pass
        pcm = (indata[:, 0] * 32768.0).astype(np.int16, copy=False) if indata.dtype != np.int16 else indata[:, 0].copy()
        try:
            self._queue.put_nowait(pcm)
        except Exception:
            # drop if backpressure
            pass

    def start(self) -> None:
        if self._stream is not None:
            return
        self._running.set()
        self._stream = sd.InputStream(
            channels=1,
            samplerate=self.samplerate,
            blocksize=self.block,
            dtype="int16",
            callback=self._callback,
            device=self.device,
        )
        self._stream.start()

    def stop(self) -> None:
        self._running.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        # drain queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    def frames(self) -> Iterator[np.ndarray]:
        while self._running.is_set():
            try:
                yield self._queue.get(timeout=0.2)
            except Exception:
                continue

