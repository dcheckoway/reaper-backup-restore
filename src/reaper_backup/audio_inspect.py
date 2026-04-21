"""
Inspect macOS Library/Audio/Plug-Ins and Library/Audio/Presets (no full dump).
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .plugin_scan import PluginBundle, scan_audio_plug_ins_dirs
from .preset_inventory import walk_audio_presets_at


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


def run_audio_inspect(
    *,
    include_system_plug_ins: bool = False,
    include_system_presets: bool = False,
    include_audio_presets: bool = True,
    max_preset_files: int | None = 10_000,
) -> dict:
    """
    Filesystem plug-in bundles under standard Audio/Plug-Ins trees, plus optional
    deep preset walk for ~/Library/Audio/Presets (and optionally /Library/.../Presets).
    """
    user_pi = paths.user_audio_plug_ins()
    user_bundles = scan_audio_plug_ins_dirs([user_pi])
    sys_bundles: list[PluginBundle] = []
    if include_system_plug_ins:
        sys_pi = paths.system_audio_plug_ins()
        if sys_pi.is_dir():
            sys_bundles = scan_audio_plug_ins_dirs([sys_pi])

    u_rows, u_by = _bundle_rows(user_bundles)
    out: dict = {
        "methodology": (
            "Plug-Ins: AU .component under Components/, VST3/.vst under VST3|VST, CLAP under CLAP/. "
            "Presets: same per-file sniff as preset-details for ~/Library/Audio/Presets (and optional system tree)."
        ),
        "plug_ins_user": {
            "root": str(user_pi.resolve()),
            "present": user_pi.is_dir(),
            "bundle_count": len(user_bundles),
            "by_format": dict(sorted(u_by.items(), key=lambda x: -x[1])),
            "bundles": u_rows,
        },
    }
    if include_system_plug_ins:
        s_rows, s_by = _bundle_rows(sys_bundles)
        out["plug_ins_system"] = {
            "root": str(paths.system_audio_plug_ins().resolve()),
            "present": paths.system_audio_plug_ins().is_dir(),
            "bundle_count": len(sys_bundles),
            "by_format": dict(sorted(s_by.items(), key=lambda x: -x[1])),
            "bundles": s_rows,
        }

    if include_audio_presets:
        out["audio_presets_user"] = walk_audio_presets_at(
            paths.user_audio_presets(),
            max_files_per_tree=max_preset_files,
        )
        if include_system_presets:
            out["audio_presets_system"] = walk_audio_presets_at(
                paths.system_audio_presets(),
                max_files_per_tree=max_preset_files,
            )
    else:
        out["audio_presets_user"] = {
            "skipped": True,
            "reason": "Audio/Presets scan disabled (--no-audio-presets)",
            "files": [],
        }

    out["reaper_resource_note"] = (
        "REAPER-specific presets live under <resource>/presets/ and Effects/*.rpl — "
        "use `reaper-backup preset-details` or `dump --preset-details`."
    )
    return out
