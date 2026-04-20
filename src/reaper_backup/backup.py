"""Lean backup: copy trees into a staging directory and write manifest.json."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import paths
from .dump_lib import collect_project_paths
from .lean import LeanOptions, should_skip_project_file, should_skip_resource_path
from .reaper_ini import extract_path_hints, parse_reaper_ini

# Restore applies layers in this order (matches RESTORE.md / plan).
LAYER_ORDER = {
    "reaper_app": 30,
    "plugins_user": 40,
    "plugins_system": 41,
    "audio_presets_user": 45,
    "audio_presets_system": 46,
    "resource": 60,
    "plist": 65,
    "project": 70,
    "extra_root": 75,
    "host_cache": 85,
    "cockos_export": 95,
}


@dataclass
class BackupConfig:
    output: Path
    resource_path: Path | None = None
    lean: LeanOptions = field(default_factory=LeanOptions)
    extra_roots: list[Path] = field(default_factory=list)
    project_roots: list[Path] = field(default_factory=list)
    include_system_plugins: bool = False
    include_system_audio_presets: bool = False
    official_export_zip: Path | None = None
    include_reaper_app: bool = False
    reaper_app_path: Path | None = None
    checksums: bool = False
    dry_run: bool = False
    home_dir: Path | None = None  # override for tests


def _home(cfg: BackupConfig) -> Path:
    return (cfg.home_dir or paths.home()).expanduser().resolve()


def _sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _merge_project_roots(cfg: BackupConfig, ini: dict[str, str]) -> list[Path]:
    """Project/media roots: CLI project roots + ini-derived paths + --extra-root trees."""
    extra = [Path(p) for p in cfg.extra_roots]
    from_ini = collect_project_paths(ini, extra)
    seen: set[str] = set()
    out: list[Path] = []
    for p in list(cfg.project_roots) + from_ini:
        k = str(p.expanduser().resolve())
        if k not in seen:
            seen.add(k)
            out.append(p.expanduser())
    return out


def run_backup(cfg: BackupConfig) -> dict:
    home_path = _home(cfg)
    if cfg.resource_path:
        resource = cfg.resource_path.expanduser().resolve()
    else:
        resource = (home_path / "Library" / "Application Support" / "REAPER").resolve()
    data_root = (cfg.output / "data").resolve()
    manifest_entries: list[dict] = []

    ini = parse_reaper_ini(resource / "reaper.ini")
    merged_project_roots = _merge_project_roots(cfg, ini)

    # --- REAPER.app ---
    app_src = (cfg.reaper_app_path or paths.default_reaper_app()).expanduser()
    if cfg.include_reaper_app and app_src.exists():
        app_dest = data_root / "reaper_app" / "REAPER.app"
        if cfg.dry_run:
            manifest_entries.append(
                {
                    "layer": "reaper_app",
                    "order": LAYER_ORDER["reaper_app"],
                    "src": "reaper_app/REAPER.app",
                    "dest_type": "root",
                    "dest_subpath": "Applications/REAPER.app",
                    "note": "Copy to /Applications/REAPER.app on destination",
                }
            )
        else:
            if app_dest.exists():
                shutil.rmtree(app_dest)
            shutil.copytree(app_src, app_dest, symlinks=True)
            manifest_entries.append(
                {
                    "layer": "reaper_app",
                    "order": LAYER_ORDER["reaper_app"],
                    "src": "reaper_app/REAPER.app",
                    "dest_type": "root",
                    "dest_subpath": "Applications/REAPER.app",
                }
            )

    # --- Resource path ---
    if resource.is_dir():
        dest_base = data_root / "resource"
        for dirpath, _dn, filenames in os.walk(resource):
            for fn in filenames:
                abs_f = Path(dirpath) / fn
                rel = PurePosixPath(abs_f.relative_to(resource).as_posix())
                if should_skip_resource_path(rel, opts=cfg.lean):
                    continue
                dst = dest_base / Path(rel.as_posix())
                try:
                    st = abs_f.stat()
                except OSError:
                    continue
                sz = st.st_size
                sha = _sha256_file(abs_f) if cfg.checksums and not cfg.dry_run else None
                manifest_entries.append(
                    {
                        "layer": "resource",
                        "order": LAYER_ORDER["resource"],
                        "src": dst.relative_to(data_root).as_posix(),
                        "dest_type": "home",
                        "dest_subpath": (
                            "Library/Application Support/REAPER/" + rel.as_posix()
                        ),
                        "size": sz,
                        **({"sha256": sha} if sha else {}),
                    }
                )
                if not cfg.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(abs_f, dst)

    # --- plist ---
    plist_src = _home(cfg) / "Library" / "Preferences" / "com.cockos.reaper.plist"
    if plist_src.is_file():
        dst = data_root / "plist" / "com.cockos.reaper.plist"
        try:
            st = plist_src.stat()
        except OSError:
            st = None
        sha = None
        if st and cfg.checksums and not cfg.dry_run:
            sha = _sha256_file(plist_src)
        manifest_entries.append(
            {
                "layer": "plist",
                "order": LAYER_ORDER["plist"],
                "src": dst.relative_to(data_root).as_posix(),
                "dest_type": "home",
                "dest_subpath": "Library/Preferences/com.cockos.reaper.plist",
                "size": st.st_size if st else 0,
                **({"sha256": sha} if sha else {}),
            }
        )
        if not cfg.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plist_src, dst)

    def _walk_layer(
        src_root: Path,
        data_rel_prefix: Path,
        layer: str,
        dest_home_subpath: str,
        *,
        dest_is_root: bool,
        use_project_skip: bool,
    ) -> None:
        if not src_root.is_dir():
            return
        dest_data_base = data_root / data_rel_prefix
        for dirpath, _dn, filenames in os.walk(src_root):
            for fn in filenames:
                abs_f = Path(dirpath) / fn
                rel = PurePosixPath(abs_f.relative_to(src_root).as_posix())
                if use_project_skip:
                    if should_skip_project_file(rel, opts=cfg.lean):
                        continue
                else:
                    from .lean import should_skip_generic_file

                    if should_skip_generic_file(abs_f, opts=cfg.lean):
                        continue
                dst = dest_data_base / rel.as_posix()
                try:
                    st = abs_f.stat()
                except OSError:
                    continue
                sz = st.st_size
                sha = _sha256_file(abs_f) if cfg.checksums and not cfg.dry_run else None
                dsp = dest_home_subpath.rstrip("/") + "/" + rel.as_posix()
                manifest_entries.append(
                    {
                        "layer": layer,
                        "order": LAYER_ORDER[layer],
                        "src": dst.relative_to(data_root).as_posix(),
                        "dest_type": "root" if dest_is_root else "home",
                        "dest_subpath": dsp,
                        "size": sz,
                        **({"sha256": sha} if sha else {}),
                    }
                )
                if not cfg.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(abs_f, dst)

    # --- host cache ---
    if cfg.lean.include_host_cache:
        _walk_layer(
            _home(cfg) / "Library" / "Caches" / "com.cockos.reaper",
            Path("host_cache") / "Library" / "Caches" / "com.cockos.reaper",
            "host_cache",
            "Library/Caches/com.cockos.reaper",
            dest_is_root=False,
            use_project_skip=False,
        )

    # --- plugins user ---
    _walk_layer(
        _home(cfg) / "Library" / "Audio" / "Plug-Ins",
        Path("plugins_user") / "Library" / "Audio" / "Plug-Ins",
        "plugins_user",
        "Library/Audio/Plug-Ins",
        dest_is_root=False,
        use_project_skip=False,
    )

    # --- plugins system ---
    if cfg.include_system_plugins:
        _walk_layer(
            paths.system_audio_plug_ins(),
            Path("plugins_system") / "Library" / "Audio" / "Plug-Ins",
            "plugins_system",
            "Library/Audio/Plug-Ins",
            dest_is_root=True,
            use_project_skip=False,
        )

    # --- audio presets user ---
    _walk_layer(
        _home(cfg) / "Library" / "Audio" / "Presets",
        Path("audio_presets_user") / "Library" / "Audio" / "Presets",
        "audio_presets_user",
        "Library/Audio/Presets",
        dest_is_root=False,
        use_project_skip=False,
    )

    # --- audio presets system ---
    if cfg.include_system_audio_presets:
        _walk_layer(
            paths.system_audio_presets(),
            Path("audio_presets_system") / "Library" / "Audio" / "Presets",
            "audio_presets_system",
            "Library/Audio/Presets",
            dest_is_root=True,
            use_project_skip=False,
        )

    # --- project trees ---
    seen_roots: set[str] = set()
    for root in merged_project_roots:
        r = root.expanduser().resolve()
        key = str(r)
        if key in seen_roots or not r.is_dir():
            continue
        seen_roots.add(key)
        slug = hashlib.sha256(key.encode()).hexdigest()[:12]
        dest_prefix = data_root / "projects" / slug
        for dirpath, _dn, filenames in os.walk(r):
            for fn in filenames:
                abs_f = Path(dirpath) / fn
                rel = PurePosixPath(abs_f.relative_to(r).as_posix())
                if should_skip_project_file(rel, opts=cfg.lean):
                    continue
                dst = dest_prefix / rel.as_posix()
                try:
                    st = abs_f.stat()
                except OSError:
                    continue
                sz = st.st_size
                sha = _sha256_file(abs_f) if cfg.checksums and not cfg.dry_run else None
                manifest_entries.append(
                    {
                        "layer": "project",
                        "order": LAYER_ORDER["project"],
                        "src": dst.relative_to(data_root).as_posix(),
                        "dest_type": "absolute",
                        "source_root": key,
                        "dest_subpath": rel.as_posix(),
                        "size": sz,
                        **({"sha256": sha} if sha else {}),
                    }
                )
                if not cfg.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(abs_f, dst)

    # --- Cockos official export zip ---
    if cfg.official_export_zip and cfg.official_export_zip.is_file():
        zsrc = cfg.official_export_zip.resolve()
        zdst = data_root / "artifacts" / "cockos_export_configuration.zip"
        try:
            st = zsrc.stat()
        except OSError:
            st = None
        sha = None
        if st and cfg.checksums and not cfg.dry_run:
            sha = _sha256_file(zsrc)
        manifest_entries.append(
            {
                "layer": "cockos_export",
                "order": LAYER_ORDER["cockos_export"],
                "src": zdst.relative_to(data_root).as_posix(),
                "dest_type": "artifact",
                "note": "Reference copy of REAPER Preferences → Export configuration; compare with config-inspect",
                "original_name": zsrc.name,
                "size": st.st_size if st else 0,
                **({"sha256": sha} if sha else {}),
            }
        )
        if not cfg.dry_run:
            zdst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zsrc, zdst)

    manifest = {
        "version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "source_home": str(home_path),
        "resource_path": str(resource),
        "path_hints": extract_path_hints(ini),
        "lean": {
            "include_plugin_scan_caches": cfg.lean.include_plugin_scan_caches,
            "include_metadata_caches": cfg.lean.include_metadata_caches,
            "include_queued_renders": cfg.lean.include_queued_renders,
            "include_host_cache": cfg.lean.include_host_cache,
            "include_peaks": cfg.lean.include_peaks,
            "exclude_project_backups": cfg.lean.exclude_project_backups,
            "full_resource_mirror": cfg.lean.full_resource_mirror,
            "include_os_metadata": cfg.lean.include_os_metadata,
        },
        "official_export_zip": str(cfg.official_export_zip.resolve())
        if cfg.official_export_zip
        else None,
        "entries": sorted(
            manifest_entries, key=lambda e: (e.get("order", 0), e.get("src", ""))
        ),
    }

    if not cfg.dry_run:
        cfg.output.mkdir(parents=True, exist_ok=True)
        man_path = cfg.output / "manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest
