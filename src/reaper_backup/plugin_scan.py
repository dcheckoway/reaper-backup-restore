"""Filesystem plug-in inventory (AU/VST/VST3/CLAP)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PluginBundle:
    format: str  # AU, VST3, VST2, CLAP
    path: Path


def _walk_plugins(root: Path, *, system: bool) -> list[PluginBundle]:
    found: list[PluginBundle] = []
    if not root.is_dir():
        return found
    # Components -> AU
    comp = root / "Components"
    if comp.is_dir():
        for p in comp.iterdir():
            if p.suffix.lower() == ".component":
                found.append(PluginBundle("AU", p))
    vst3 = root / "VST3"
    if vst3.is_dir():
        for p in vst3.rglob("*.vst3"):
            if p.is_dir():
                found.append(PluginBundle("VST3", p))
    vst = root / "VST"
    if vst.is_dir():
        for p in vst.glob("*.vst"):
            found.append(PluginBundle("VST2", p))
        for p in vst.glob("*.vst3"):
            if p.is_dir():
                found.append(PluginBundle("VST3", p))
    clap = root / "CLAP"
    if clap.is_dir():
        for p in clap.iterdir():
            if p.is_file() or p.suffix:
                found.append(PluginBundle("CLAP", p))
    return found


def scan_audio_plug_ins_dirs(paths: list[Path]) -> list[PluginBundle]:
    out: list[PluginBundle] = []
    for i, root in enumerate(paths):
        out.extend(_walk_plugins(root, system=(i > 0)))
    return sorted(out, key=lambda x: str(x.path).lower())
