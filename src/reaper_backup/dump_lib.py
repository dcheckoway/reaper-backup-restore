"""Build discovery / dump payload as a dict (JSON-serializable)."""

from __future__ import annotations

import os
from pathlib import Path

from . import paths
from .plugin_scan import scan_audio_plug_ins_dirs
from .reaper_ini import extract_path_hints, parse_reaper_ini, unique_parent_dirs
from .rpp import parse_rpp


def walk_resource_files(root: Path) -> list[dict]:
    """All files under root with relative posix path, size, mtime."""
    out: list[dict] = []
    if not root.is_dir():
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            out.append(
                {
                    "path": rel,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )
    return sorted(out, key=lambda x: x["path"])


def collect_project_paths(
    ini: dict[str, str],
    extra_roots: list[Path],
) -> list[Path]:
    hints = extract_path_hints(ini)
    all_paths: list[str] = []
    all_paths.extend(hints["recent_and_tabs"])
    all_paths.extend(hints["last_project"])
    all_paths.extend(hints["path_keys"])
    dirs = unique_parent_dirs([p for p in all_paths if p])
    roots: list[Path] = []
    for d in dirs:
        roots.append(Path(d).expanduser())
    for r in extra_roots:
        roots.append(r.expanduser())
    # dedupe
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots:
        k = str(r.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def glob_sidecars(root: Path) -> dict[str, int]:
    """Count *.reapeaks and *.rpp-bak under root (recursive)."""
    if not root.is_dir():
        return {"reapeaks": 0, "rpp_bak": 0}
    peaks = 0
    bak = 0
    for dirpath, _dn, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".reapeaks"):
                peaks += 1
            if fn.lower().endswith(".rpp-bak"):
                bak += 1
    return {"reapeaks": peaks, "rpp_bak": bak}


def find_rpp_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _dn, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(".rpp"):
                    found.append(Path(dirpath) / fn)
    return sorted(found)


def plugin_scan_cache_files(resource_path: Path) -> list[dict]:
    """List known REAPER plug-in scan-cache INIs under the resource path (metadata only)."""
    patterns = (
        "reaper-vstplugins_*.ini",
        "reaper-auplugins*.ini",
        "reaper-jsfx.ini",
        "reaper-clap-*.ini",
        "reaper-recentfx.ini",
    )
    found: list[Path] = []
    for pat in patterns:
        found.extend(resource_path.glob(pat))
    out: list[dict] = []
    for p in sorted({p.resolve() for p in found}):
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append(
            {
                "path": p.relative_to(resource_path).as_posix(),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
    return out


def run_dump(
    *,
    resource_path: Path | None = None,
    project_roots: list[Path] | None = None,
    extra_roots: list[Path] | None = None,
    rpp_details: bool = False,
    rpp_limit: int = 50,
) -> dict:
    resource_path = resource_path or paths.default_resource_path()
    extra_roots = extra_roots or []
    project_roots = project_roots or []

    ini_path = resource_path / "reaper.ini"
    ini = parse_reaper_ini(ini_path)
    merged_roots = list(project_roots) + collect_project_paths(ini, extra_roots)

    plug_roots = [paths.user_audio_plug_ins()]
    sys_pi = paths.system_audio_plug_ins()
    if sys_pi.is_dir():
        plug_roots.append(sys_pi)
    plugins = scan_audio_plug_ins_dirs(plug_roots)

    payload: dict = {
        "resource_path": str(resource_path.resolve()),
        "reaper_plist": {
            "path": str(paths.default_reaper_plist().resolve()),
            "exists": paths.default_reaper_plist().is_file(),
        },
        "host_cache": {
            "path": str(paths.default_host_cache().resolve()),
            "exists": paths.default_host_cache().is_dir(),
        },
        "reaper_ini": {k: ini[k] for k in sorted(ini.keys())[:200]} if ini else {},
        "path_hints": extract_path_hints(ini),
        "resource_files": walk_resource_files(resource_path),
        "audio_plug_ins": {
            "user": str(paths.user_audio_plug_ins()),
            "system": str(paths.system_audio_plug_ins()),
        },
        "plugins_fs": [
            {"format": p.format, "path": str(p.path.resolve())} for p in plugins
        ],
        "plugin_scan_cache_files": plugin_scan_cache_files(resource_path),
        "audio_presets_user": str(paths.user_audio_presets()),
        "audio_presets_user_exists": paths.user_audio_presets().is_dir(),
        "project_roots_checked": [str(p.resolve()) for p in merged_roots],
        "sidecars_by_root": {
            str(r.resolve()): glob_sidecars(r) for r in merged_roots if r.is_dir()
        },
        "rpp_files": [str(p.resolve()) for p in find_rpp_files(merged_roots)],
    }

    if rpp_details:
        details = []
        for p in find_rpp_files(merged_roots)[:rpp_limit]:
            try:
                s = parse_rpp(p)
                details.append(
                    {
                        "path": str(p.resolve()),
                        "reaper_version": s.reaper_version,
                        "track_count": len(s.tracks),
                        "tracks": s.tracks,
                        "master_fx": s.master_fx,
                    }
                )
            except OSError as e:
                details.append({"path": str(p.resolve()), "error": str(e)})
        payload["rpp_details"] = details

    return payload


def resource_relative_set(dump: dict) -> set[str]:
    """Build set of relative paths from dump['resource_files']."""
    return {x["path"].replace("\\", "/") for x in dump.get("resource_files", [])}
