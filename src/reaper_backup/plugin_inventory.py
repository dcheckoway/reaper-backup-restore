"""
Installed plug-in inventory: standard macOS Audio/Plug-Ins trees + optional REAPER UserPlugins.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import paths
from .plugin_scan import PluginBundle, scan_audio_plug_ins_dirs


def _bundle_rows(bundles: list[PluginBundle]) -> tuple[list[dict], dict[str, int]]:
    rows: list[dict] = []
    by_fmt: dict[str, int] = {}
    for b in bundles:
        by_fmt[b.format] = by_fmt.get(b.format, 0) + 1
        row: dict = {
            "format": b.format,
            "path": str(b.path.resolve()),
            "bundle_name": b.path.name,
        }
        try:
            st = b.path.stat()
            row["mtime"] = int(st.st_mtime)
        except OSError as e:
            row["stat_error"] = str(e)
        rows.append(row)
    return rows, by_fmt


def _userplugins_files(
    root: Path,
    *,
    max_files: int,
) -> tuple[list[dict], bool]:
    """List files under UserPlugins (extensions, JS DLLs, etc.), relative paths."""
    out: list[dict] = []
    truncated = False
    if not root.is_dir():
        return out, False
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if len(out) >= max_files:
                truncated = True
                return out, truncated
            abs_p = Path(dirpath) / fn
            try:
                rel = abs_p.relative_to(root)
            except ValueError:
                continue
            row: dict = {"path": str(rel.as_posix())}
            try:
                st = abs_p.stat()
                row["size"] = st.st_size
                row["mtime"] = int(st.st_mtime)
            except OSError as e:
                row["stat_error"] = str(e)
            out.append(row)
    out.sort(key=lambda r: r.get("path", "").lower())
    return out, truncated


def run_plugin_inventory(
    *,
    include_system: bool = False,
    include_reaper_userplugins: bool = True,
    resource_path: Path | None = None,
    userplugins_max_files: int = 5000,
) -> dict:
    """
    Filesystem plug-ins under ~/Library/Audio/Plug-Ins (and optionally /Library/...),
    plus optional REAPER ``UserPlugins`` under the resource folder.

    Does not read REAPER preferences for custom VST search paths — only fixed locations.
    """
    resource = paths.resolve_resource_path(resource_path)
    user_pi = paths.user_audio_plug_ins()
    user_bundles = scan_audio_plug_ins_dirs([user_pi])
    u_rows, u_by = _bundle_rows(user_bundles)

    out: dict = {
        "methodology": (
            "AU: Library/Audio/Plug-Ins/Components/*.component; "
            "VST3: …/VST3/*.vst3; VST2: …/VST/*.vst; CLAP: …/CLAP/*"
        ),
        "notes": [
            "Custom additional VST paths set inside REAPER are not scanned — only these trees.",
        ],
        "plug_ins_user": {
            "root": str(user_pi.resolve()),
            "present": user_pi.is_dir(),
            "bundle_count": len(user_bundles),
            "by_format": dict(sorted(u_by.items(), key=lambda x: -x[1])),
            "bundles": u_rows,
        },
    }

    if include_system:
        sys_pi = paths.system_audio_plug_ins()
        sys_bundles: list[PluginBundle] = []
        if sys_pi.is_dir():
            sys_bundles = scan_audio_plug_ins_dirs([sys_pi])
        s_rows, s_by = _bundle_rows(sys_bundles)
        out["plug_ins_system"] = {
            "root": str(sys_pi.resolve()),
            "present": sys_pi.is_dir(),
            "bundle_count": len(sys_bundles),
            "by_format": dict(sorted(s_by.items(), key=lambda x: -x[1])),
            "bundles": s_rows,
        }

    up_root = resource / "UserPlugins"
    if include_reaper_userplugins:
        files, truncated = _userplugins_files(up_root, max_files=userplugins_max_files)
        out["reaper_userplugins"] = {
            "root": str(up_root.resolve()),
            "present": up_root.is_dir(),
            "file_count": len(files),
            "truncated": truncated,
            "files": files,
        }

    sys_count = (
        out["plug_ins_system"]["bundle_count"]
        if include_system and "plug_ins_system" in out
        else 0
    )
    rup = out.get("reaper_userplugins") or {}
    out["summary"] = {
        "audio_plug_ins_bundle_count": len(user_bundles) + sys_count,
        "reaper_userplugins_file_count": rup.get("file_count", 0),
    }

    return out
