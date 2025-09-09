from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StatusEvent:
    message: str
    level_db: Optional[float] = None
    vad_active: Optional[bool] = None


@dataclass
class FinalEvent:
    text: str
    latency_ms: Optional[int] = None

