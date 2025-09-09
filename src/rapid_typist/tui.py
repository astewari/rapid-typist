from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


@dataclass
class TUIState:
    model: str = "base.en"
    sink: str = "clipboard"
    device: str = "default"
    hotkey: str = "fn"
    recording: bool = False
    vad_active: bool = False
    level_db: float = 0.0
    partial_text: str = ""
    last_text: str = ""
    last_latency_ms: Optional[int] = None


class TUI:
    def __init__(self) -> None:
        self.console = Console()
        self.state = TUIState()
        self._live: Optional[Live] = None

    def start(self) -> None:
        self._live = Live(self._render(), console=self.console, refresh_per_second=8)
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        t = Table.grid(expand=True)
        t.add_row(
            f"[bold]rapid-typist[/] — model=[cyan]{self.state.model}[/] sink=[magenta]{self.state.sink}[/] device=[green]{self.state.device}[/] hotkey=[blue]{self.state.hotkey}[/]"
        )
        rec = "[green]● recording[/]" if self.state.recording else "[red]○ idle[/]"
        vad = "[yellow]speech[/]" if self.state.vad_active else "silence"
        level = f"{self.state.level_db:6.1f} dB"
        t.add_row(f"{rec} | VAD: {vad} | lvl: {level}")
        if self.state.partial_text:
            t.add_row(f"partial: [dim]{self.state.partial_text}[/]")
        if self.state.last_text:
            lat = (
                f" ({self.state.last_latency_ms} ms)" if self.state.last_latency_ms is not None else ""
            )
            t.add_row(f"last: [white]{self.state.last_text}[/]{lat}")
        return Panel(t, title="rapid-typist")


class NoopTUI:
    def __init__(self) -> None:
        self.state = TUIState()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def update(self, **kwargs) -> None:
        # Update internal state only; no rendering
        for k, v in kwargs.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)
