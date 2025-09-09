from __future__ import annotations

import numpy as np


def int16_to_float32(pcm: np.ndarray) -> np.ndarray:
    if pcm.dtype != np.int16:
        pcm = pcm.astype(np.int16, copy=False)
    return (pcm.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


def rms_dbfs(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return -120.0
    x = pcm.astype(np.float32) / 32768.0
    rms = np.sqrt(np.mean(x * x) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-12)
    return float(db)

