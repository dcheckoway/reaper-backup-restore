"""Parse reaper.ini for path-like keys."""

from __future__ import annotations

import re
from pathlib import Path


_PATH_KEYS = (
    "defsavepath",
    "defrecpath",
    "defrenderpath",
    "autosavedir",
    "autosavedir_unsaved",
    "importpath",
    "altpeakspath",
    "altpeaksopathlist",
    "midiexportpath",
)


def parse_reaper_ini(path: Path) -> dict[str, str]:
    """Return key -> value for non-empty lines key=value."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        out[k] = v
    return out


def extract_path_hints(ini: dict[str, str]) -> dict[str, list[str]]:
    """Collect interesting paths grouped by category."""
    recent: list[str] = []
    for k, v in ini.items():
        if k.startswith("recent") and v and ("/" in v or v.endswith(".RPP") or v.endswith(".rpp")):
            if v.startswith("/") or v.startswith("~"):
                recent.append(v)
        if k.startswith("projecttab") and v and "/" in v:
            recent.append(v)
    last = []
    for key in ("lastproject", "lastprojuiref"):
        v = ini.get(key, "")
        if v and ("/" in v):
            last.append(v)
    roots: list[str] = []
    for key in _PATH_KEYS:
        v = ini.get(key, "")
        if v and "/" in v:
            roots.append(v)
    return {
        "recent_and_tabs": recent,
        "last_project": last,
        "path_keys": roots,
    }


def unique_parent_dirs(paths: list[str]) -> list[str]:
    """Best-effort parent directories for globbing projects."""
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        expanded = str(Path(p).expanduser())
        try:
            parent = str(Path(expanded).parent)
        except Exception:
            continue
        if parent not in seen:
            seen.add(parent)
            out.append(parent)
    return out
