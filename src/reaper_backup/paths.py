"""Default macOS paths for REAPER and audio plug-ins."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.path.expanduser("~"))


def default_resource_path() -> Path:
    return home() / "Library" / "Application Support" / "REAPER"


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
