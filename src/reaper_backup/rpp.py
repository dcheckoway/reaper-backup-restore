"""Parse REAPER .RPP project files (line-oriented, best-effort)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


_NAME_RE = re.compile(r"^\s+NAME\s+\"([^\"]*)\"")
_FX_RE = re.compile(r"^\s+<(AU|VST|VST3|JS|CLAP)\s+")


@dataclass
class RppSummary:
    reaper_version: str | None = None
    tracks: list[dict] = field(default_factory=list)
    master_fx: list[str] = field(default_factory=list)


def _parse_fx_title(line: str) -> str | None:
    line = line.strip()
    if not line.startswith("<"):
        return None
    rest = line[1:].strip()
    space = rest.find(" ")
    if space == -1:
        return None
    rest2 = rest[space + 1 :].strip()
    if not rest2.startswith('"'):
        return None
    end = rest2.find('"', 1)
    if end <= 0:
        return None
    return rest2[1:end]


def parse_rpp(path: Path) -> RppSummary:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = RppSummary()
    if lines:
        first = lines[0].strip()
        if first.startswith("<REAPER_PROJECT"):
            parts = first.split()
            if len(parts) >= 3:
                summary.reaper_version = parts[2].strip('"')

    try:
        first_track = next(i for i, l in enumerate(lines) if l.strip().startswith("<TRACK"))
    except StopIteration:
        first_track = len(lines)

    try:
        master_start = next(i for i, l in enumerate(lines[:first_track]) if "<MASTERFXLIST" in l)
    except StopIteration:
        master_start = 0

    for line in lines[master_start:first_track]:
        if _FX_RE.match(line):
            t = _parse_fx_title(line)
            if t:
                summary.master_fx.append(t)

    if first_track >= len(lines):
        return summary

    rest_text = "\n".join(lines[first_track:])
    segments = re.split(r"(?m)^(?=<TRACK \{)", rest_text)
    for seg in segments:
        seg = seg.strip()
        if not seg.startswith("<TRACK"):
            continue
        m = _NAME_RE.search(seg)
        name = m.group(1) if m else None
        fx: list[str] = []
        for line in seg.splitlines():
            if _FX_RE.match(line):
                t = _parse_fx_title(line)
                if t:
                    fx.append(t)
        summary.tracks.append({"name": name, "fx": fx})

    return summary
