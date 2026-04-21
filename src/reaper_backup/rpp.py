"""Parse REAPER .RPP project files (line-oriented, best-effort)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


_NAME_RE = re.compile(r'(?m)^\s+NAME\s+"([^"]*)"')
_NAME_UNQUOTED_RE = re.compile(r"(?m)^\s+NAME\s+([^\r\n]+?)\s*$")


def _parse_track_name(seg: str) -> str | None:
    m = _NAME_RE.search(seg)
    if m:
        return m.group(1)
    m2 = _NAME_UNQUOTED_RE.search(seg)
    if m2:
        return m2.group(1).strip()
    return None
_FX_RE = re.compile(r"^\s+<(AU|VST|VST3|JS|CLAP)\s+")
_PRESETNAME_RE = re.compile(r'^\s+PRESETNAME\s+"(.*)"\s*$')
_BYPASS_LINE_RE = re.compile(r"^\s+BYPASS\s+(\d+)")
_CLOSE_CHUNK_RE = re.compile(r"^\s+>\s*$")


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


def _parse_fx_chain_lines(lines: list[str]) -> list[dict]:
    """
    Extract FX slots from a block of .rpp lines (e.g. MASTERFXLIST or track FXCHAIN).
    Each slot: format, plugin (display title), preset (from PRESETNAME if present), bypassed.
    """
    out: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _FX_RE.match(line)
        if not m:
            i += 1
            continue
        fmt = m.group(1)
        title = _parse_fx_title(line)
        slot: dict = {
            "format": fmt,
            "plugin": title,
            "preset": None,
            "bypassed": False,
        }
        i += 1
        while i < n and not _CLOSE_CHUNK_RE.match(lines[i]):
            i += 1
        if i < n:
            i += 1
        while i < n:
            l2 = lines[i]
            if _FX_RE.match(l2):
                break
            pm = _PRESETNAME_RE.match(l2)
            if pm:
                slot["preset"] = pm.group(1)
                i += 1
                continue
            bm = _BYPASS_LINE_RE.match(l2)
            if bm:
                slot["bypassed"] = bm.group(1) != "0"
                i += 1
                continue
            i += 1
        out.append(slot)
    return out


def parse_rpp_project_inspect(path: Path) -> dict:
    """
    Per-FX detail for master + each track: plugin format/title, PRESETNAME, bypass flag.
    Best-effort line scan; unusual .rpp variants may omit fields.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    reaper_version: str | None = None
    if lines:
        first = lines[0].strip()
        if first.startswith("<REAPER_PROJECT"):
            parts = first.split()
            if len(parts) >= 3:
                reaper_version = parts[2].strip('"')

    try:
        first_track = next(i for i, l in enumerate(lines) if l.strip().startswith("<TRACK"))
    except StopIteration:
        first_track = len(lines)

    try:
        master_start = next(
            i for i, l in enumerate(lines[:first_track]) if "<MASTERFXLIST" in l
        )
    except StopIteration:
        master_start = first_track

    master_lines = lines[master_start:first_track]
    master_fx = _parse_fx_chain_lines(master_lines)

    tracks_out: list[dict] = []
    if first_track < len(lines):
        rest_text = "\n".join(lines[first_track:])
        segments = re.split(r"(?m)^\s*(?=<TRACK \{)", rest_text)
        tidx = 0
        for seg in segments:
            seg = seg.strip()
            if not seg.startswith("<TRACK"):
                continue
            name = _parse_track_name(seg)
            fx = _parse_fx_chain_lines(seg.splitlines())
            tracks_out.append(
                {
                    "track_index": tidx,
                    "name": name,
                    "fx": fx,
                }
            )
            tidx += 1

    return {
        "path": str(path.resolve()),
        "reaper_version": reaper_version,
        "master": {"fx": master_fx},
        "tracks": tracks_out,
    }


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
        master_start = first_track

    for line in lines[master_start:first_track]:
        if _FX_RE.match(line):
            t = _parse_fx_title(line)
            if t:
                summary.master_fx.append(t)

    if first_track >= len(lines):
        return summary

    rest_text = "\n".join(lines[first_track:])
    segments = re.split(r"(?m)^\s*(?=<TRACK \{)", rest_text)
    for seg in segments:
        seg = seg.strip()
        if not seg.startswith("<TRACK"):
            continue
        name = _parse_track_name(seg)
        fx: list[str] = []
        for line in seg.splitlines():
            if _FX_RE.match(line):
                t = _parse_fx_title(line)
                if t:
                    fx.append(t)
        summary.tracks.append({"name": name, "fx": fx})

    return summary
