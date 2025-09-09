# rapid-typist — Local Voice→Text for macOS (Apple Silicon)

**Owner:** @astewari  
**Status:** Draft v1 (implementation-ready)  
**Target platform:** macOS 14+ on Apple Silicon (M3 validated; M1/M2 expected)  
**Language:** Python 3.11+  
**Package manager:** `uv` (Astral)  
**Upstream inspiration:** [whisper-writer] — minimal dictation UX we’ll borrow ideas from (push-to-talk, simple text buffer), but re-implement in Python with a more modular architecture.

---

## 0) Problem Statement & Goals
We want a **fast, private, local** dictation tool that runs entirely on an Apple Silicon Mac and **streams** recognized text into any target sink (stdout/TUI, clipboard, or paste into the frontmost app). The app should:

- Start/stop recording via a **configurable global hotkey** (toggle: press once to start, press again to stop).
- Perform on‑device transcription using Whisper models (Backend A = **openai‑whisper**), with near‑real‑time partials and finalized transcripts.
- Provide **a lightweight menu bar runner** to show status and quick controls.
- Be robust to background noise (basic VAD / endpointing) and handle long sessions.
- Make installation simple with `uv` + Homebrew.

**Non‑goals (v1):**
- ❌ Speaker diarization or speaker attribution.  
- ❌ Production‑grade packaging/notarization — ship a CLI + lightweight menubar runner.

**Stretch goals:**
- 🌐 **Multilingual transcription**, with priority for **English and Hindi** (language auto‑detection and/or profile switching).  
- Inline command vocabulary ("new line", "comma").

---

## 1) High‑Level Architecture

```
+---------------------+       +-------------------+       +------------------+       +-------------------------+
| Mic Capture (Core)  |  PCM  |  VAD/Endpointing  | WAV   |  Transcribe Eng. | JSON  |  Output Sinks / Adapters|
|  • sounddevice      +------->  • py-webrtcvad    +------->  • Whisper       +------->  • stdout / TUI           |
|  • 16kHz mono       |       |  • segmenter       |       |    (backend sel) |       |  • clipboard/paste      |
+----------+----------+       +---------+---------+       +----+----+---------+       |  • file (.md, .txt)     |
           ^                              |                        |                  |  • socket/HTTP (opt)    |
           |                              v                        v                  +-------------------------+
           |                     +-------------------+     +-------------------+
           |                     |  Ring Buffer      |     |  Post‑Processor   |
           |                     |  (async queues)   |     |  (punct, timestamps,
           |                     +-------------------+     |   language tag)   |
           |                                               +-------------------+
```

### 1.1 Components
- **Mic Capture:** `sounddevice` (PortAudio) in callback mode; 16kHz mono frames; auto‑request mic permission on first run.
- **VAD/Endpointing:** `py-webrtcvad` gate + hangover to form speech segments; tune aggressiveness (0–3) per user setting.
- **Transcribe Engine (Backend‑pluggable):**
  - **Backend A – openai‑whisper (PyTorch/MPS):** Favours compatibility; supports Metal via PyTorch `mps` device; good accuracy.
  - **Backend B – whisper.cpp via `pywhispercpp` (CoreML/MLX capable):** Very fast on Apple Silicon; small memory footprint; excellent for streaming.
  - **Backend C – faster‑whisper (CTranslate2/CPU):** Fast on CPU for small/medium models; a solid fallback; (GPU via CUDA only — not for Apple Silicon).
- **Post‑Processor:** apply model timestamps, optional word timestamps, finalization rules (stable text vs partials), punctuation/casing (built‑in to Whisper models), normalizers for numbers (e.g., “twenty five”→“25”, optional).
- **Output Sinks:** stdout/TUI, clipboard, paste‑into‑frontmost app (scriptable), file writer, optional local HTTP server for integrations.

---

## 2) UX & User Flows

### 2.1 First‑run Setup
1) `uv` will bootstrap the project; a first run will:
   - Check Homebrew & FFmpeg presence; if missing, prompt with the one‑liner.
   - Ask for mic; macOS shows the permission dialog.
2) Minimal TUI prints device list and default mic; user can change with `--input-device`.

### 2.2 Dictation Modes
- **Global Hotkey (toggle):** Start recording when the hotkey is pressed; keep recording until the hotkey is pressed again (or an explicit stop command). Silence/VAD still defines segment boundaries within an active session.

### 2.3 Output Destinations
- **stdout/TUI:** Stream partials and print finalized text.
- **Clipboard:** Copy finalized text automatically for manual paste.
- **Paste‑into‑frontmost app (scriptable):** After each finalized segment, synthesize a paste (⌘V) to the focused field.

> Behavior: After a segment finalizes, the system **auto‑sends** the text to the **selected sink** (stdout/TUI, clipboard, or paste). Partials are shown in TUI only. Output Destinations
- **Clipboard:** collect finalized text and append to clipboard; user pastes when ready.
- **Auto‑paste:** after each finalized segment, synthesize a paste (⌘V) into the focused field.
- **File:** append to `.md` or `.txt` in a chosen directory.
- **Socket/HTTP (opt):** POST each segment to `http://localhost:<port>/transcript`.

### 2.4 Status & Feedback
- TUI shows live levels (ASCII meter), VAD state, partial transcript, model, latency, and CPU load.
- Audible “start/stop” tick (optional).

---

## 3) Detailed Design

### 3.1 Audio Pipeline
- **Sample rate:** 16,000 Hz; mono; 16‑bit PCM.
- **Frame size:** 30 ms (480 samples @16k); VAD supports 10/20/30 ms — pick 30 ms for fewer callbacks.
- **Buffers:** Lock‑free ring buffer feeding a segmenter coroutine; limit total buffered audio (e.g., 10s) to cap latency.
- **VAD:** Aggressiveness (0…3), hangover (e.g., 300 ms), pre‑roll (e.g., 150 ms) so we don’t clip leading phonemes.

### 3.2 Segmenter & Streaming
- Maintain **active segment** until VAD reports silence for `hangover_ms`; then finalize.
- For **streaming partials**: either
  - (a) feed rolling windows (e.g., last 3–5s) to the model and diff outputs, or
  - (b) use backend’s incremental decode (whisper.cpp supports fast partials).
- Emit events: `on_partial`, `on_final`, `on_error`, `on_status` via an internal event bus.

### 3.3 Transcription Backends
- **Backend A: openai‑whisper**
  - Device: `mps` (Metal) when available; else `cpu`.
  - Models: `tiny`, `base`, `small`, `medium`, `large-v3` (default: `small` for speed).
  - Pros: high accuracy, stable; Cons: heavier runtime.
- **Backend B: pywhispercpp (whisper.cpp)**
  - Backends: CPU by default; supports CoreML / MLX builds; tiny memory; great throughput for streaming.
  - Models: GGML/GGUF variants (`tiny.en`, `base.en`, `small.en`, etc.).
  - Pros: best perf on M‑series; Cons: fewer Pythonic knobs vs PyTorch.
- **Backend C: faster‑whisper**
  - Engine: CTranslate2; on Apple Silicon typically CPU bound (still fast for `tiny`/`base`).
  - Pros: efficient CPU inference; Cons: no Metal GPU; large models may be slower than whisper.cpp.

Backends are swappable behind a common `Transcriber` interface:
```python
class Transcriber(Protocol):
    async def transcribe(self, pcm: np.ndarray, is_final: bool) -> TranscriptionEvent: ...
    async def finalize(self) -> None: ...
```

### 3.4 Post‑Processing Rules
- Stabilize partials: only emit a word when we’ve seen it repeated N times (or time‑anchored) to reduce jitter.
- Normalize whitespace; keep punctuation from model; optional number normalization.
- “Smart spacing” around punctuation; merge short segments (< 300 ms) into neighbors.
- Optional **Auto‑capitalize** first word of finalized segment if model outputs lowercased text.

### 3.5 Output Sinks (Adapters)
- **stdout/TUI sink:** prints partials and finals; configurable separator (space/newline).
- **Clipboard sink:** copies each finalized segment; optional joiner when batching.
- **Paste sink (frontmost app):** issues ⌘V via `osascript`/`pyobjc` immediately after finalization.

### 3.6 Config & Profiles Config & Profiles
`~/.rapid_typist.toml`:
```toml
[app]
mode = "push_to_talk"        # push_to_talk | toggle | hands_free
hotkey = "right_option"       # one of: right_option, caps_lock, f18, etc.
input_device = "default"

[engine]
backend = "pywhispercpp"      # openai_whisper | pywhispercpp | faster_whisper
model = "base.en"             # per backend naming
language = "en"
word_timestamps = false

[vad]
aggressiveness = 2            # 0..3
frame_ms = 30
hangover_ms = 300
preroll_ms = 150

[output]
sINK = "clipboard"            # clipboard | paste | file | http
file_dir = "~/Documents/Dictation"
separator = "\n"
```

---

## 4) CLI & Menubar

### 4.1 CLI
```
uv run rapid-typist --mode hotkey --backend openai-whisper --model base \
  --sink paste --hotkey right_option --language auto --vad 2
```
Commands:
- `devices list` — list input devices.
- `profiles ls/add/rm/set` — manage config profiles.
- `run` — start the pipeline with current profile.
- `bench` — run a short benchmark on a static WAV to estimate RTF (real‑time factor).

### 4.2 Menu bar runner (lightweight)
- Tray mic icon with live state (idle/recording), model selector, device selector, hotkey display, quick quit.
- Implement with `rumps` or `pyobjc`; launched as `uv run rapid-typist-menubar`.

---

## 5) Installation & Environment

### 5.1 Prereqs (macOS)
- **Homebrew + FFmpeg:**
  - Install Homebrew if needed, then `brew install ffmpeg`.
- **(Optional) System audio capture:** If you want to transcribe system audio, install **BlackHole** (virtual device) and select it as the input.

### 5.2 Project Bootstrap (with `uv`)
```
# 1) Create project and venv
uv init rapid-typist
cd rapid-typist

# 2) Add runtime deps
uv add numpy sounddevice py-webrtcvad rich click pydantic
uv add --group engines openai-whisper

# 3) (Optional) for dev tools
uv add --group dev black ruff mypy pytest pytest-asyncio

# 4) Run
uv run python -m rapid_typist --help
```

### 5.3 `pyproject.toml` (starter)
```toml
[project]
name = "rapid-typist"
version = "0.1.0"
description = "Local, streaming speech-to-text for macOS (Apple Silicon)"
authors = [{ name = "Ashrut Tewari", email = "astewari@conviva.com" }]
requires-python = ">=3.11"
readme = "README.md"

[project.scripts]
rapid-typist = "rapid_typist.cli:main"
rapid-typist-menubar = "rapid_typist.menubar:main"
```

---

## 6) Directory Layout
```
rapid-typist/
  ├─ rapid_typist/
  │   ├─ __init__.py
  │   ├─ cli.py                # click CLI
  │   ├─ config.py             # Pydantic config
  │   ├─ audio/
  │   │    ├─ capture.py       # sounddevice callback → ring buffer
  │   │    ├─ vad.py           # py-webrtcvad segmenter
  │   │    └─ utils.py
  │   ├─ engines/
  │   │    ├─ base.py          # Transcriber protocol
  │   │    ├─ openai_whisper.py
  │   │    ├─ pywhispercpp.py
  │   │    └─ faster_whisper.py
  │   ├─ sinks/
  │   │    ├─ base.py
  │   │    ├─ clipboard.py
  │   │    ├─ paste.py
  │   │    ├─ file.py
  │   │    └─ http.py
  │   ├─ events.py             # dataclasses for Partial/Final/Status
  │   └─ tui.py                # live status (rich)
  ├─ tests/
  │   ├─ test_vad.py
  │   ├─ test_segmentation.py
  │   └─ test_engines.py
  ├─ README.md
  ├─ pyproject.toml
  └─ LICENSE
```

---

## 7) Key Implementation Notes

### 7.1 Microphone Permissions
- First run from Terminal will trigger the macOS microphone permission dialog.

### 7.2 Latency Targets
- **Capture→partial**: < 300 ms for short utterances on `base`.
- **Capture→final**: < 800 ms after end of speech for VAD hangover 300 ms.

### 7.3 Model Asset Management
- On first run, download selected model; cache under `~/Library/Application Support/rapid-typist/models`.
- Expose `rapid-typist models list/pull/rm` commands.

### 7.4 Hotkeys
- **Global toggle** bound by default to Right‑Option; configurable.
- Global hotkeys implemented via `pyobjc` (preferred) or `pynput` fallback.

### 7.5 Stability & Resilience
- Long‑running tasks as `asyncio` coroutines; graceful shutdown on SIGINT.
- Watchdog on the audio callback; if back‑pressure rises, drop partials (never block audio thread).
- Structured logging with `rich`.

---

## 8) Accuracy & Tuning
- Prefer `.en` English models for speed/accuracy if the language is known.
- If environment is noisy, set VAD aggressiveness to 3 and increase pre‑roll to 200 ms.
- Consider adding a light text normalizer for numbers & ordinals in a later patch.

---

## 9) Testing (pragmatic)
- **Smoke tests:** quick microphone capture → VAD gates → engine returns text on a 10–20 s utterance.
- **Boundary tests:** start/stop via hotkey rapidly; ensure no crashes and paste/clipboard behavior is correct.
- **Bench:** measure RTF on a short sample for `tiny`/`base`.

---

## 10) Security & Privacy
- All processing is on‑device; no audio or text leaves the machine unless HTTP sink is enabled.
- Config and model cache stored under the user’s Library folder.

---

## 11) Roadmap (post‑v1)
- 🌐 **Multilingual support** with priority for **English and Hindi** (auto‑detect, or quick language toggle).
- Inline command vocabulary ("new line", "comma").
- Packaging & notarization for drag‑and‑drop install.
- (Future) Diarization and speaker attribution (explicitly **out of scope** for v1).

---

## 12) Acceptance Criteria (v1)
- ✅ CLI starts; first‑run creates config & downloads selected model (`openai‑whisper`).
- ✅ **Global hotkey** toggle works and produces text with < 1s perceived latency.
- ✅ Hands‑free segmentation inside an active session via VAD; minimal clipping.
- ✅ Output sinks limited to **stdout/TUI**, **clipboard**, and **paste** — selectable via config/CLI.
- ✅ Lightweight menu bar runner shows status and allows quick start/stop.

---

## 13) Reference Commands & Snippets

### 13.1 sounddevice capture (skeleton)
```python
import sounddevice as sd, numpy as np
from collections import deque

RATE = 16000
BLOCK = int(0.03 * RATE)  # 30ms
buf = deque(maxlen=RATE * 10)

def cb(indata, frames, time, status):
    if status: print(status)
    buf.extend(indata[:, 0].copy())

with sd.InputStream(callback=cb, channels=1, samplerate=RATE, blocksize=BLOCK, dtype='int16'):
    sd.sleep(10_000)
```

### 13.2 VAD gate (py‑webrtcvad)
```python
import webrtcvad
vad = webrtcvad.Vad(2)  # 0..3
# feed 10/20/30ms 16-bit mono @16k frames; True == speech
```

### 13.3 openai‑whisper usage (simplified)
```python
import whisper
model = whisper.load_model("base")
result = model.transcribe("segment.wav", language="en")
print(result["text"]) 
```

---

## 14) Risks & Mitigations
- **Mic permission quirks** → instruct first run via Terminal.
- **Throughput on larger models** on CPU → default to `base`.
- **FFmpeg missing** → explicit check on startup with clear remediation.

---

## 15) How We Differ from whisper-writer
- Python toolchain with `uv`.
- Pluggable architecture, but **Backend A = openai‑whisper** for v1.
- Streaming partials and multi‑sink outputs (**stdout/TUI**, **clipboard**, **paste**).
- CLI‑first plus a lightweight **menu bar** runner.

> Reference repo for inspiration when in doubt: https://github.com/savbell/whisper-writer

---

## 16) Appendix — Commands the Implementer Should Run
```bash
# Install Homebrew (if missing) and ffmpeg
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg

# Bootstrap with uv
uv init rapid-typist && cd rapid-typist
uv add numpy sounddevice py-webrtcvad rich click pydantic
uv add --group engines openai-whisper

# Verify mic works and list devices
uv run python -c "import sounddevice as sd; print(sd.query_devices())"

# First run
uv run rapid-typist --mode hotkey --backend openai-whisper --model base --sink paste
```

---

## 17) Parallel Workstreams (develop & test in parallel)

**WS‑A: Audio I/O & VAD (owner A)**
- Implement `capture.py` with sounddevice callback → ring buffer.
- Implement `vad.py` with py‑webrtcvad (aggressiveness/frames/hangover/preroll) and segmenter.
- Minimal TUI meters; emit `on_partial/on_final` placeholders.

**WS‑B: Transcription Engine (owner B)**
- Implement `engines/openai_whisper.py` with batch + rolling‑window partials.
- Model cache/loader; language config (en, hi planned later).

**WS‑C: Output Sinks (owner C)**
- Implement `stdout`, `clipboard`, `paste` adapters with a common base.
- Auto‑send finalized segments to the selected sink.

**WS‑D: CLI & Config (owner D)**
- Click‑based CLI, profile loader, device listing, bench command.

**WS‑E: Menu Bar Runner (owner E)**
- Minimal tray app with start/stop, device/model pickers, status.

**WS‑F: Glue & QA (shared)**
- Integrate events → engine → sinks; smoke tests; latency spot checks.

> **Git policy:** push all commits to remote `ashrut-fork` (feature branches per workstream, open PRs for review).

