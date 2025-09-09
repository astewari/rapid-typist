# AGENTS.md — Guide for Future Coding Agents

This repository contains a macOS Apple Silicon, Python 3.11+ project for local, streaming speech‑to‑text with a CLI and menubar app. It runs fully on‑device, defaults to whisper.cpp via `pywhispercpp` with Metal acceleration, and streams finalized text to paste/clipboard/stdout/file. This document captures decisions, structure, and expectations so future Codex sessions can act consistently and safely.

## Golden Rules
- Target Python `>=3.11,<3.13` only. Do not downgrade or add Python 3.9 support.
- The transcription backend is whisper.cpp via `pywhispercpp` only. Do not re‑add `openai-whisper`, Torch, or CUDA.
- Keep the src/ layout. All runtime modules live under `src/rapid_typist/`. Tests live under `tests/`.
- Default model is `base.en`; the CLI and menubar must also allow selecting `large-v3` and other typical ggml models.
- Default sink is `paste`. Do not change this unless the user asks.
- Default hotkey is double Fn (Globe). Implement via Quartz event tap; fall back to Right‑Option double‑press if Quartz tap fails. Ensure Accessibility guidance is present.
- Keep changes minimal and focused. Do not introduce unrelated tooling or dependencies.

## Project Structure (src/ layout)
- `src/rapid_typist/`
  - `cli.py` — Click CLI (`rapid-typist` entry point)
  - `menubar.py` — rumps menubar app (`rapid-typist-menubar`)
  - `config.py` — pydantic models; TOML load/save at `~/.rapid_typist.toml`
  - `tui.py` — Rich TUI (and `NoopTUI` for menubar use)
  - `hotkey.py` — global hotkey listeners (Quartz Fn x2 + pynput fallback)
  - `events.py` — simple dataclasses (Status/Final)
  - `audio/`
    - `capture.py` — sounddevice callback, 16 kHz mono, 30 ms frames
    - `vad.py` — py‑webrtcvad segmenter with hangover + preroll; `monitor()` yields (seg, active, level)
    - `utils.py` — PCM conversions + dBFS
  - `engines/`
    - `base.py` — `Transcriber` protocol
    - `whispercpp_backend.py` — `WhisperCppTranscriber` using `pywhispercpp.Model`
  - `sinks/`
    - `base.py` — `Sink` protocol
    - `stdout.py`, `clipboard.py`, `paste.py`, `file.py`
- `tests/` — keep light; example `test_imports.py`
- `pyproject.toml` — setuptools build, scripts, dependencies

## Dependencies
- Required runtime deps:
  - `pywhispercpp>=1.1.0` (whisper.cpp; auto‑Metal)
  - `sounddevice>=0.5`, `webrtcvad>=2.0.10`
  - `click`, `rich`, `pydantic`
  - `pynput` (fallback hotkey), `pyobjc-framework-Quartz` (Quartz event tap via rumps dependency chain)
  - `rumps` (menubar)
  - `numpy>=1.26,<2.0`
- Removed & must not reintroduce: `openai-whisper`, `torch`, `faster-whisper`.
- Build system: setuptools; packages discovered from `src`.

## Configuration
- User config path: `~/.rapid_typist.toml`
- Defaults (v1):
  - `[app]` mode = "toggle"; `hotkey = "fn"`; `input_device = "default"`
  - `[engine]` backend = "whispercpp"; `model = "base.en"`; `language="en"`
  - `[vad]` aggressiveness=2; frame_ms=30; hangover_ms=300; preroll_ms=150
  - `[output]` sink="paste"; file_dir, separator="\n"
- Editing config triggers pipeline restart in menubar actions.

## CLI
- Entrypoint: `rapid-typist`
- Commands:
  - `devices list` — list input devices
  - `run` — start pipeline; options:
    - `--sink` `[stdout|clipboard|paste|file]`
    - `--model` e.g., `base.en`, `large-v3`
    - `--language` (passes through to engine)
    - `--hotkey` ("fn" uses Quartz double‑press; others map to `pynput`)
    - `--input-device` (name or "default")
    - `--partials/--no-partials` (TUI partials from rolling window; not sent to sinks)
  - `bench` — record N seconds and compute RTF; respects `--model`, `--language`, `--input-device`.

## Menubar
- Entrypoint: `rapid-typist-menubar`
- Menu:
  - Start/Stop (toggle pipeline)
  - Status line (Idle / Listening… / Partial/Last text preview)
  - Sink (stdout/clipboard/paste/file)
  - Model (tiny(.en), base(.en), small(.en), large-v3)
  - Input Device (list w/ Refresh)
  - VAD Aggressiveness (0–3)
  - Hotkey label (updates if fallback active)
  - Open Config…, Open Accessibility Settings, Quit
- Hotkey: attempts Fn double‑press via Quartz (requires Accessibility + set Fn to "Do nothing"). If tap creation fails, falls back to Right‑Option double‑press and updates the label.
- Uses `NoopTUI` with the same `Pipeline` as CLI.

## Pipeline & Partials
- Audio: 16 kHz mono, 30 ms frames, non‑blocking queue; drops frames under backpressure.
- VAD segmenter: aggressiveness (0–3), hangover, preroll. `monitor()` yields `(segment_or_none, vad_active, level_dbfs)` so TUI updates align with live frames.
- Engine: `WhisperCppTranscriber` (`pywhispercpp.Model`). On init, it prints system info and whisper.cpp logs show Metal usage.
- Partials: background thread transcribes a rolling ~5s window every ~1s while VAD is active. Holds a lock to avoid contention with final decode; clears the ring on finalize.
- Finals: only finals go to sinks; TUI shows last text + latency.

## Installation & Run (dev)
- Prereqs: macOS 14+ on Apple Silicon; Homebrew `ffmpeg` recommended; grant Microphone + Accessibility permissions.
- Suggested flow with `uv`:
  - `uv python install 3.11.9`
  - `uv venv -p 3.11.9 --clear && source .venv/bin/activate`
  - `uv pip install -e .`
  - `rapid-typist devices list`
  - `rapid-typist run --model base.en` (press Fn twice to toggle)
  - `rapid-typist bench --seconds 5 --model large-v3`

## Troubleshooting
- Fn hotkey not working:
  - System Settings → Keyboard → set Globe/Fn to "Do nothing".
  - Grant Accessibility permission to your terminal app. Use menubar → Open Accessibility Settings.
  - Menubar falls back to Right‑Option double‑press if Quartz tap cannot be created.
- Whisper.cpp GPU/Metal:
  - On first model load, logs should include “using device Metal” and “using Metal backend”. If not, `pywhispercpp` may have built without Metal; reinstall or update.
- Large models:
  - `large-v3` allocates ~3 GB on Metal; initial load takes time. Prefer `base.en` for low‑latency.

## Coding Conventions
- Keep public APIs stable (CLI flags, config keys, entry points).
- New code goes under `src/rapid_typist/…`; add tests under `tests/`.
- Avoid adding heavy dependencies; prefer stdlib and existing libs.
- Prefer small, focused modules; avoid inline comments except where essential.
- Logging: concise `print()` lines prefixed with `[rapid-typist]` for lifecycle and engine/device info.

## Non‑Goals (v1) — Do Not Add Without Explicit Approval
- No diarization/speaker ID; no HTTP server sink; no model management commands (beyond basic load).
- No reintroduction of PyTorch/Torch MPS or openai‑whisper.
- No packaging/notarization changes (CLI + menubar only).

## What’s Been Verified
- Bench on Python 3.11 with `pywhispercpp` shows Metal backend in logs and high RTF.
- Menubar launches, hotkey listener starts, and fallback works if tap fails.
- CLI supports `--model large-v3` and other ggml models.

## Nice‑to‑Haves (Future Work)
- Expose `pywhispercpp` params (threads, best_of) in config/CLI/menubar.
- Model prefetch/remove commands.
- More unit tests (VAD boundaries, segmentation, sinks).

