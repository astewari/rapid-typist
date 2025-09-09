rapid-typist — Local Voice→Text for macOS (Apple Silicon)

Quick start
- Ensure Homebrew ffmpeg is installed: `brew install ffmpeg`
- Create a Python 3.9 environment (uv/venv) and install deps: `uv pip install -e .`
- First run: `uv run rapid-typist run` (grants mic & accessibility on demand)

Defaults
- Backend: whisper.cpp via `whispercpp` (auto Metal/CoreML if available); falls back to openai-whisper on Python 3.9 if whispercpp wheel is unavailable
- Sink: paste (finalized segments only)
- Hotkey: double Fn (press Fn twice to toggle)
- VAD: 30ms frames, aggressiveness=2, hangover=300ms, preroll=150ms

Commands
- `rapid-typist devices list` — List input devices
- `rapid-typist run` — Start the pipeline; toggle via global hotkey
- `rapid-typist bench` — Record N seconds and report RTF
- `rapid-typist-menubar` — Minimal tray app to start/stop

Notes
- Streaming partials shown in TUI (rolling 5s window, ~1s cadence). Partials are not sent to sinks.
- You may need to grant Accessibility permission for global hotkeys and paste automation.
 - For Fn double-press: In System Settings → Keyboard, set Globe/Fn action to "Do nothing" (to avoid conflicts with emoji/dictation), then grant Accessibility.

Menu bar
- Launch: `source .venv/bin/activate && rapid-typist-menubar`
- Shows: Start/Stop, Sink (stdout/clipboard/paste/file), Model, Input Device (with Refresh), VAD aggressiveness, Hotkey, Open Config, Accessibility, Quit.
- Status indicator in the title: ● recording, ○ idle. Partial/last text preview in menu.

Examples
- Benchmark 5 seconds: `uv run rapid-typist bench`
- Run without partials (finals only): `uv run rapid-typist run --no-partials`
  - Note: Project targets Python 3.9 with openai-whisper.
