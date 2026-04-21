"""Default macOS paths for REAPER and audio plug-ins."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.path.expanduser("~"))


def default_resource_path(*, home_dir: Path | None = None) -> Path:
    root = home_dir.expanduser().resolve() if home_dir is not None else home()
    return root / "Library" / "Application Support" / "REAPER"


def resolve_resource_path(
    explicit: Path | None = None,
    *,
    home_dir: Path | None = None,
) -> Path:
    """
    REAPER resource folder: explicit CLI path, else REAPER_RESOURCE_PATH env,
    else <home>/Library/Application Support/REAPER.
    """
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get("REAPER_RESOURCE_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return default_resource_path(home_dir=home_dir).resolve()


def default_reaper_plist() -> Path:
    return home() / "Library" / "Preferences" / "com.cockos.reaper.plist"


def default_host_cache() -> Path:
    return home() / "Library" / "Caches" / "com.cockos.reaper"


def user_audio_plug_ins() -> Path:
    return home() / "Library" / "Audio" / "Plug-Ins"


def user_audio_presets() -> Path:
    return home() / "Library" / "Audio" / "Presets"


def system_audio_plug_ins() -> Path:
    return Path("/Library/Audio/Plug-Ins")


def system_audio_presets() -> Path:
    return Path("/Library/Audio/Presets")


def default_reaper_app() -> Path:
    return Path("/Applications/REAPER.app")
