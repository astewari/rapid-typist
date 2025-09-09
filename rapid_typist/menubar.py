from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Optional

import rumps
import sounddevice as sd

from .cli import Pipeline
from .config import load_config, save_config
from .tui import NoopTUI
from .hotkey import create_hotkey_listener


MODEL_CHOICES = [
    "tiny.en",
    "base.en",
    "small.en",
    "tiny",
    "base",
    "small",
    "large-v3",
]


class MenuBarApp(rumps.App):
    def __init__(self):
        super().__init__("rapid-typist", quit_button=None)
        self.title = "○ rapid-typist"
        self.cfg = load_config()
        self.pipeline = Pipeline(cfg=self.cfg, tui=NoopTUI(), device_name=self.cfg.app.input_device, enable_partials=False)
        self.listener = None
        # Startup diagnostics
        print(
            "[rapid-typist] menubar:",
            "engine=", self.cfg.engine.backend,
            "model=", self.cfg.engine.model,
            "sink=", self.cfg.output.sink,
            "input=", self.cfg.app.input_device,
            "hotkey=", self.cfg.app.hotkey,
        )

        # Menu items
        self.mi_toggle = rumps.MenuItem("Start Recording", callback=self._on_toggle)
        self.mi_sink = rumps.MenuItem("Sink")
        self.mi_model = rumps.MenuItem("Model")
        self.mi_device = rumps.MenuItem("Input Device")
        self.mi_vad = rumps.MenuItem("VAD Aggressiveness")
        self.mi_hotkey = rumps.MenuItem(f"Hotkey: {self.cfg.app.hotkey}")
        self.mi_status = rumps.MenuItem("Status: Idle")
        self.mi_open_cfg = rumps.MenuItem("Open Config…", callback=self._open_config)
        self.mi_accessibility = rumps.MenuItem("Open Accessibility Settings", callback=self._open_accessibility)
        self.mi_quit = rumps.MenuItem("Quit", callback=self._quit)

        # Attach menu skeleton first (so submenus can be populated/cleared)
        self.menu = [
            self.mi_toggle,
            None,
            self.mi_status,
            None,
            self.mi_sink,
            self.mi_model,
            self.mi_device,
            self.mi_vad,
            self.mi_hotkey,
            self.mi_open_cfg,
            self.mi_accessibility,
            None,
            self.mi_quit,
        ]

        # Populate submenus
        self._build_sink_menu()
        self._build_model_menu()
        self._build_device_menu()
        self._build_vad_menu()

        # Start hotkey listener (double Fn by default)
        try:
            self.listener = create_hotkey_listener(self.cfg.app.hotkey, self.pipeline.toggle)
            self.listener.start()
        except Exception:
            pass

        # Periodic UI updates
        self._timer = rumps.Timer(self._tick, 0.5)
        self._timer.start()

    def _tick(self, _):
        if getattr(self.pipeline, "_active", False):
            self.title = "● rapid-typist"
            self.mi_toggle.title = "Stop Recording"
            # update status with partials or last final
            try:
                st = self.pipeline.tui.state
                if st.partial_text:
                    txt = st.partial_text
                    if len(txt) > 40:
                        txt = txt[:37] + "..."
                    self.mi_status.title = f"Partial: {txt}"
                elif st.last_text:
                    txt = st.last_text
                    if len(txt) > 40:
                        txt = txt[:37] + "..."
                    self.mi_status.title = f"Last: {txt}"
                else:
                    self.mi_status.title = "Status: Listening…"
            except Exception:
                self.mi_status.title = "Status: Listening…"
        else:
            self.title = "○ rapid-typist"
            self.mi_toggle.title = "Start Recording"
            self.mi_status.title = "Status: Idle"
        # update sink/model/device checks
        self._sync_checks()

    # Menu builders
    def _build_sink_menu(self):
        def make_sink_item(name: str):
            return rumps.MenuItem(name, callback=lambda _: self._set_sink(name))

        try:
            self.mi_sink.clear()
        except Exception:
            pass
        for name in ["stdout", "clipboard", "paste", "file"]:
            self.mi_sink.add(make_sink_item(name))

    def _build_model_menu(self):
        def make_model_item(name: str):
            return rumps.MenuItem(name, callback=lambda _: self._set_model(name))

        try:
            self.mi_model.clear()
        except Exception:
            pass
        for name in MODEL_CHOICES:
            self.mi_model.add(make_model_item(name))

    def _build_device_menu(self):
        try:
            self.mi_device.clear()
        except Exception:
            pass

        def make_device_item(name: str):
            return rumps.MenuItem(name, callback=lambda _: self._set_device(name))

        # default option
        self.mi_device.add(make_device_item("default"))
        try:
            devs = sd.query_devices()
            for d in devs:
                if int(d.get("max_input_channels", 0)) > 0:
                    self.mi_device.add(make_device_item(d["name"]))
        except Exception:
            pass
        self.mi_device.add(rumps.MenuItem("Refresh", callback=lambda _: self._build_device_menu()))

    def _build_vad_menu(self):
        try:
            self.mi_vad.clear()
        except Exception:
            pass
        for val in [0, 1, 2, 3]:
            self.mi_vad.add(rumps.MenuItem(str(val), callback=lambda _, v=val: self._set_vad(v)))

    def _sync_checks(self):
        # sink
        for name, item in self.mi_sink.items():
            if isinstance(item, rumps.MenuItem):
                item.state = int(name == self.cfg.output.sink)
        # model
        for name, item in self.mi_model.items():
            if isinstance(item, rumps.MenuItem):
                item.state = int(name == self.cfg.engine.model)
        # device
        for name, item in self.mi_device.items():
            if isinstance(item, rumps.MenuItem) and name not in ("Refresh",):
                item.state = int(name == (self.cfg.app.input_device or "default"))
        # vad
        for name, item in self.mi_vad.items():
            if isinstance(item, rumps.MenuItem):
                try:
                    item.state = int(int(name) == self.cfg.vad.aggressiveness)
                except Exception:
                    item.state = 0

    # Actions
    def _on_toggle(self, _):
        self.pipeline.toggle()

    def _restart_pipeline(self):
        was_active = getattr(self.pipeline, "_active", False)
        if was_active:
            self.pipeline.stop()
            time.sleep(0.2)
        # Create new pipeline with updated cfg
        self.pipeline = Pipeline(cfg=self.cfg, tui=NoopTUI(), device_name=self.cfg.app.input_device, enable_partials=False)
        if was_active:
            self.pipeline.start()

    def _set_sink(self, name: str):
        self.cfg.output.sink = name  # type: ignore
        save_config(self.cfg)
        self._restart_pipeline()

    def _set_model(self, name: str):
        self.cfg.engine.model = name
        save_config(self.cfg)
        self._restart_pipeline()

    def _set_device(self, name: str):
        self.cfg.app.input_device = name
        save_config(self.cfg)
        self._restart_pipeline()

    def _set_vad(self, val: int):
        self.cfg.vad.aggressiveness = int(val)
        save_config(self.cfg)
        self._restart_pipeline()

    def _open_config(self, _):
        cfgp = os.path.expanduser("~/.rapid_typist.toml")
        subprocess.run(["open", cfgp])

    def _open_accessibility(self, _):
        # Open Accessibility settings panel
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])  # noqa: E501

    def _quit(self, _):
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass
        try:
            if getattr(self.pipeline, "_active", False):
                self.pipeline.stop()
        except Exception:
            pass
        rumps.quit_application()


def main():
    MenuBarApp().run()
