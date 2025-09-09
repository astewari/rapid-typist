from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


ConfigMode = Literal["push_to_talk", "toggle", "hands_free"]
SinkName = Literal["stdout", "clipboard", "paste", "file"]


class AppConfig(BaseModel):
    mode: ConfigMode = Field(default="toggle")
    hotkey: str = Field(default="fn")
    input_device: str = Field(default="default")


class EngineConfig(BaseModel):
    backend: Literal["openai_whisper", "whispercpp"] = Field(default="whispercpp")
    model: str = Field(default="base.en")
    language: str = Field(default="en")
    word_timestamps: bool = Field(default=False)


class VadConfig(BaseModel):
    aggressiveness: int = Field(default=2, ge=0, le=3)
    frame_ms: int = Field(default=30)
    hangover_ms: int = Field(default=300)
    preroll_ms: int = Field(default=150)


class OutputConfig(BaseModel):
    sink: SinkName = Field(default="paste")
    file_dir: str = Field(default=str(Path.home() / "Documents/Dictation"))
    separator: str = Field(default="\n")


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    vad: VadConfig = Field(default_factory=VadConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


DEFAULT_TOML = """
[app]
mode = "toggle"
hotkey = "fn"
input_device = "default"

[engine]
backend = "whispercpp"
model = "base.en"
language = "en"
word_timestamps = false

[vad]
aggressiveness = 2
frame_ms = 30
hangover_ms = 300
preroll_ms = 150

[output]
sink = "paste"
file_dir = "~/Documents/Dictation"
separator = "\n"
"""


def config_path() -> Path:
    # Keep config in home as per spec; project files remain here.
    return Path.home() / ".rapid_typist.toml"


def load_config() -> Config:
    cfg_path = config_path()
    if not cfg_path.exists():
        cfg_path.write_text(DEFAULT_TOML.strip() + "\n", encoding="utf-8")

    # Python <3.11 uses tomli; >=3.11 uses tomllib
    try:
        import tomllib as _toml  # type: ignore
    except Exception:  # pragma: no cover - py39 fallback
        import tomli as _toml  # type: ignore

    data = _toml.loads(cfg_path.read_text(encoding="utf-8"))
    return Config.model_validate(data)


def save_config(cfg: Config) -> None:
    # Minimal TOML writer for our flat schema.
    cfg_path = config_path()
    sep = cfg.output.separator.encode("unicode_escape").decode("ascii")
    content = (
        "[app]\n"
        f"mode = \"{cfg.app.mode}\"\n"
        f"hotkey = \"{cfg.app.hotkey}\"\n"
        f"input_device = \"{cfg.app.input_device}\"\n\n"
        "[engine]\n"
        f"backend = \"{cfg.engine.backend}\"\n"
        f"model = \"{cfg.engine.model}\"\n"
        f"language = \"{cfg.engine.language}\"\n"
        f"word_timestamps = {str(cfg.engine.word_timestamps).lower()}\n\n"
        "[vad]\n"
        f"aggressiveness = {cfg.vad.aggressiveness}\n"
        f"frame_ms = {cfg.vad.frame_ms}\n"
        f"hangover_ms = {cfg.vad.hangover_ms}\n"
        f"preroll_ms = {cfg.vad.preroll_ms}\n\n"
        "[output]\n"
        f"sink = \"{cfg.output.sink}\"\n"
        f"file_dir = \"{cfg.output.file_dir}\"\n"
        f"separator = \"{sep}\"\n"
    )
    cfg_path.write_text(content, encoding="utf-8")
