from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class HotkeyListener:
    def start(self) -> None:  # pragma: no cover - small glue
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - small glue
        raise NotImplementedError


class PynputHotkeyListener(HotkeyListener):
    def __init__(self, key, on_toggle: Callable[[], None], double: bool = False, interval: float = 0.6) -> None:
        from pynput import keyboard

        self._keyboard = keyboard
        self._key = key
        self._on_toggle = on_toggle
        self._double = double
        self._interval = interval
        self._last = 0.0
        self._listener: Optional[keyboard.Listener] = None

    def _on_press(self, key):
        if key == self._key:
            now = time.time()
            if self._double:
                if now - self._last <= self._interval:
                    self._on_toggle()
                    self._last = 0.0
                else:
                    self._last = now
            else:
                # debounce
                if now - self._last > 0.4:
                    self._on_toggle()
                    self._last = now

    def start(self) -> None:
        self._listener = self._keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None


class FnDoublePressListener(HotkeyListener):
    """Listen for a double Fn (Globe) key press using a Quartz event tap.
    Requires Accessibility permission. Best-effort; falls back if unavailable.
    """

    def __init__(self, on_toggle: Callable[[], None], interval: float = 0.6) -> None:
        self._on_toggle = on_toggle
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._loop = None
        self._last_press = 0.0
        self._tap = None

    def start(self) -> None:
        try:
            import Quartz
        except Exception:
            raise RuntimeError("Quartz not available for Fn capture")

        def tap_callback(proxy, type_, event, refcon):
            try:
                flags = Quartz.CGEventGetFlags(event)
                # Prefer kCGEventFlagMaskSecondaryFn if available
                fnmask = getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0x00080000)  # fallback mask value
                pressed = bool(flags & fnmask)
                if pressed:
                    now = time.time()
                    if now - self._last_press <= self._interval:
                        self._on_toggle()
                        self._last_press = 0.0
                    else:
                        self._last_press = now
            except Exception:
                pass
            return event

        def runloop():
            mask = 1 << 12  # kCGEventFlagsChanged
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                mask,
                tap_callback,
                None,
            )
            if not self._tap:
                return
            source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopDefaultMode)
            Quartz.CGEventTapEnable(self._tap, True)
            Quartz.CFRunLoopRun()

        self._thread = threading.Thread(target=runloop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            import Quartz
        except Exception:
            return
        if self._loop is not None:
            try:
                Quartz.CFRunLoopStop(self._loop)
            except Exception:
                pass
            self._loop = None
        self._thread = None


def create_hotkey_listener(spec: str, on_toggle: Callable[[], None]) -> HotkeyListener:
    spec = spec.lower()
    if spec in ("fn", "globe"):
        try:
            return FnDoublePressListener(on_toggle)
        except Exception:
            # fallback to right_option double press
            from pynput.keyboard import Key

            return PynputHotkeyListener(Key.alt_r, on_toggle, double=True)
    else:
        # map names to pynput keys
        from pynput.keyboard import Key

        mapping = {
            "right_option": Key.alt_r,
            "left_option": Key.alt,
            "caps_lock": Key.caps_lock,
            "f18": Key.f18,
            "f19": Key.f19,
        }
        key = mapping.get(spec, Key.alt_r)
        return PynputHotkeyListener(key, on_toggle, double=False)


