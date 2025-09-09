from __future__ import annotations

import signal
import sys
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Optional

import click
import numpy as np
import sounddevice as sd
from pynput import keyboard

from .config import Config, load_config
from .tui import TUI
from .audio.capture import AudioCapture
from .audio.vad import Segmenter
from .engines.whispercpp_backend import WhisperCppTranscriber
from .sinks.base import Sink
from .sinks.stdout import StdoutSink
from .sinks.clipboard import ClipboardSink
from .sinks.paste import PasteSink
from .sinks.file import FileSink
from .audio.utils import rms_dbfs
from .hotkey import create_hotkey_listener
from collections import deque


SINKS = {
    "stdout": StdoutSink,
    "clipboard": ClipboardSink,
    "paste": PasteSink,
    "file": FileSink,
}


@dataclass
class Pipeline:
    cfg: Config
    tui: TUI
    device_name: Optional[str] = None
    enable_partials: bool = True

    def __post_init__(self):
        self._active = False
        self._stop_evt = threading.Event()
        self._threads: list[threading.Thread] = []
        self._segments: "Queue[np.ndarray]" = Queue(maxsize=8)
        self._level_db: float = -120.0
        self._vad_active: bool = False

    def start(self):
        if self._active:
            return
        self._stop_evt.clear()
        self._active = True
        self.tui.update(recording=True)
        print("[rapid-typist] Pipeline: start")

        # Build components
        capture = AudioCapture(
            samplerate=16000,
            block_ms=self.cfg.vad.frame_ms,
            device=None if self.device_name in (None, "default") else self.device_name,
        )
        segmenter = Segmenter(
            aggressiveness=self.cfg.vad.aggressiveness,
            frame_ms=self.cfg.vad.frame_ms,
            hangover_ms=self.cfg.vad.hangover_ms,
            preroll_ms=self.cfg.vad.preroll_ms,
            samplerate=16000,
        )
        # Engine selection: whispercpp only (Python 3.11 target)
        engine = WhisperCppTranscriber(model_name=self.cfg.engine.model, language=self.cfg.engine.language)
        print("[rapid-typist] Engine: whisper.cpp")
        engine_lock = threading.Lock()

        sink_name = self.cfg.output.sink
        if sink_name == "file":
            sink: Sink = FileSink(self.cfg.output.file_dir, separator=self.cfg.output.separator)
        else:
            sink = SINKS[sink_name]()  # type: ignore

        # Partial streaming buffers (rolling window)
        window_sec = 5.0
        cadence_sec = 1.0
        min_sec = 1.2
        frames_per_window = int(window_sec * (1000.0 / self.cfg.vad.frame_ms))
        partial_ring = deque(maxlen=frames_per_window)

        def runner_capture():
            capture.start()
            for pcm in capture.frames():
                self._level_db = rms_dbfs(pcm)
                if self._stop_evt.is_set():
                    break
                try:
                    # feed to segmenter chain
                    frame_queue.put(pcm, timeout=0.1)
                except Exception:
                    pass
                # keep partial ring
                partial_ring.append(pcm)
            capture.stop()

        def runner_segmenter():
            for seg, active, level in segmenter.monitor(_iter_queue(frame_queue, self._stop_evt)):
                self._vad_active = active
                self._level_db = level
                self.tui.update(vad_active=active, level_db=level)
                if self._stop_evt.is_set():
                    break
                if seg is not None:
                    try:
                        self._segments.put(seg, timeout=0.1)
                    except Exception:
                        pass

        def runner_infer():
            while not self._stop_evt.is_set():
                try:
                    seg = self._segments.get(timeout=0.2)
                except Exception:
                    continue
                t0 = time.time()
                with engine_lock:
                    text = engine.transcribe(seg)
                latency = int((time.time() - t0) * 1000)
                if text:
                    sink.handle_final(text)
                    # clear partial on final and reset rolling buffer
                    partial_ring.clear()
                    self.tui.update(partial_text="", last_text=text, last_latency_ms=latency)

        def runner_partials():
            last_emit = 0.0
            while not self._stop_evt.is_set():
                time.sleep(0.1)
                if not self.enable_partials:
                    continue
                if not self._vad_active:
                    # clear lingering partial if idle
                    if self.tui.state.partial_text:
                        self.tui.update(partial_text="")
                    continue
                now = time.time()
                if now - last_emit < cadence_sec:
                    continue
                # gather rolling window
                frames = list(partial_ring)
                if not frames:
                    continue
                audio = np.concatenate(frames)
                dur = len(audio) / 16000.0
                if dur < min_sec:
                    continue
                # try non-blocking lock to avoid contention with finals
                locked = engine_lock.acquire(blocking=False)
                if not locked:
                    continue
                try:
                    text = engine.transcribe(audio)
                    if text:
                        self.tui.update(partial_text=text)
                        last_emit = now
                finally:
                    engine_lock.release()

        frame_queue: "Queue[np.ndarray]" = Queue(maxsize=64)

        t1 = threading.Thread(target=runner_capture, daemon=True)
        t2 = threading.Thread(target=runner_segmenter, daemon=True)
        t3 = threading.Thread(target=runner_infer, daemon=True)
        t4 = threading.Thread(target=runner_partials, daemon=True)
        self._threads = [t1, t2, t3, t4]
        for t in self._threads:
            t.start()

    def stop(self):
        if not self._active:
            return
        self._stop_evt.set()
        for t in self._threads:
            t.join(timeout=1.5)
        self._threads.clear()
        self._active = False
        self.tui.update(recording=False)
        print("[rapid-typist] Pipeline: stop")

    def toggle(self):
        if self._active:
            self.stop()
        else:
            self.start()


def _iter_queue(q: "Queue[np.ndarray]", stop_evt: threading.Event):
    while not stop_evt.is_set():
        try:
            yield q.get(timeout=0.2)
        except Exception:
            continue


def _map_hotkey(name: str):
    # Minimal mapping for common keys
    name = name.lower()
    from pynput.keyboard import Key

    mapping = {
        "right_option": Key.alt_r,
        "left_option": Key.alt,
        "caps_lock": Key.caps_lock,
        "f18": Key.f18,
        "f19": Key.f19,
    }
    return mapping.get(name, Key.alt_r)


@click.group()
def cli():
    """rapid-typist CLI."""


@cli.group()
def devices():
    """Device utilities."""


@devices.command("list")
def devices_list():
    devs = sd.query_devices()
    default = sd.default.device
    click.echo(f"Default devices (in,out): {default}")
    for i, d in enumerate(devs):
        click.echo(f"[{i:02d}] {d['name']} — in:{d['max_input_channels']} out:{d['max_output_channels']}")


@cli.command()
@click.option("--seconds", type=int, default=5, help="Record N seconds for the benchmark.")
@click.option("--model", type=str, help="Override model (e.g., base.en)")
@click.option("--language", type=str, help="Override language (e.g., en)")
@click.option("--input-device", type=str, default=None, help="Input device name or 'default'.")
def bench(seconds: int, model: Optional[str], language: Optional[str], input_device: Optional[str]):
    """Run a short microphone benchmark and report RTF (audio_dur / compute_time)."""
    cfg = load_config()
    if model:
        cfg.engine.model = model
    if language:
        cfg.engine.language = language
    if input_device:
        cfg.app.input_device = input_device

    sr = 16000
    blocks = []
    cap = AudioCapture(samplerate=sr, block_ms=cfg.vad.frame_ms, device=None if cfg.app.input_device in (None, "default") else cfg.app.input_device)
    click.echo(f"Recording {seconds}s @ {sr} Hz from '{cfg.app.input_device}'...")
    cap.start()
    collected = 0
    target = seconds * sr
    try:
        for pcm in cap.frames():
            blocks.append(pcm)
            collected += len(pcm)
            if collected >= target:
                break
    finally:
        cap.stop()

    if not blocks:
        click.echo("No audio captured. Mic permission granted?")
        return

    audio = np.concatenate(blocks)
    audio_sec = len(audio) / sr
    click.echo(f"Captured {audio_sec:.2f}s audio. Loading model '{cfg.engine.model}'...")
    eng = WhisperCppTranscriber(model_name=cfg.engine.model, language=cfg.engine.language)
    click.echo("Transcribing...")
    t0 = time.time()
    text = eng.transcribe(audio)
    t1 = time.time()
    compute = t1 - t0
    rtf = audio_sec / compute if compute > 0 else 0.0
    click.echo(f"Done. compute={compute:.2f}s, audio={audio_sec:.2f}s, RTF={rtf:.2f}")
    if text:
        preview = text if len(text) < 160 else text[:157] + "..."
        click.echo(f"Preview: {preview}")


@cli.command()
@click.option("--sink", type=click.Choice(["stdout", "clipboard", "paste", "file"]))
@click.option("--model", type=str)
@click.option("--language", type=str)
@click.option("--hotkey", type=str)
@click.option("--input-device", type=str, default=None)
@click.option("--partials/--no-partials", default=True, help="Show streaming partials in TUI")
def run(sink: Optional[str], model: Optional[str], language: Optional[str], hotkey: Optional[str], input_device: Optional[str], partials: bool):
    """Start the pipeline and toggle recording with a global hotkey (default: right_option)."""
    cfg = load_config()
    if sink:
        cfg.output.sink = sink  # type: ignore
    if model:
        cfg.engine.model = model
    if language:
        cfg.engine.language = language
    if hotkey:
        cfg.app.hotkey = hotkey
    if input_device:
        cfg.app.input_device = input_device

    # Startup log
    print(
        "[rapid-typist] run:",
        "engine=", cfg.engine.backend,
        "model=", cfg.engine.model,
        "sink=", cfg.output.sink,
        "input=", cfg.app.input_device,
        "hotkey=", cfg.app.hotkey,
    )

    tui = TUI()
    tui.start()
    tui.update(model=cfg.engine.model, sink=cfg.output.sink, device=cfg.app.input_device, hotkey=cfg.app.hotkey)
    pipeline = Pipeline(cfg=cfg, tui=tui, device_name=cfg.app.input_device, enable_partials=partials)

    # Hotkey listener (support Fn x2 via Quartz if requested)
    if cfg.app.hotkey.lower() in ("fn", "globe"):
        click.echo("Hotkey: double Fn — press Fn twice to toggle (grant Accessibility; disable macOS Dictation/Globe key conflicts if needed).")
    else:
        click.echo(f"Hotkey: {cfg.app.hotkey} — press to toggle.")

    listener = create_hotkey_listener(cfg.app.hotkey, pipeline.toggle)
    try:
        listener.start()
    except Exception as e:
        click.echo(f"Hotkey init failed: {e}. Falling back to Right-Option.")
        listener = create_hotkey_listener("right_option", pipeline.toggle)
        listener.start()

    def handle_sigint(signum, frame):
        try:
            listener.stop()
        except Exception:
            pass
        pipeline.stop()
        tui.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    # Run until interrupted
    try:
        while True:
            time.sleep(0.2)
    finally:
        try:
            listener.stop()
        except Exception:
            pass
        pipeline.stop()
        tui.stop()


def main():
    cli()
