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
from .progress import make_log
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
    # When True (CLI --comprehensive): full resource mirror + host cache + all lean opt-ins.
    comprehensive: bool = False
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
    verbose: bool = True


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


def _coverage_notes(cfg: BackupConfig) -> list[str]:
    """Human-readable description of what this backup run captured (vs dump / export-audit)."""
    lean = cfg.lean
    lines: list[str] = []
    if lean.full_resource_mirror:
        lines.append(
            "REAPER resource (Application Support/…/REAPER): full tree — presets/ (.ini VST/AU state), "
            "Effects/ (JSFX + .rpl), FXChains/, Scripts/, Data/, UserPlugins/, KeyMaps/, ColorThemes/, OSC/, "
            "MIDINoteNames/, etc. Excludes only OS junk (.DS_Store, ._* ) unless --include-os-metadata."
        )
    else:
        lines.append(
            "REAPER resource: lean — skips MetadataCaches/, QueuedRenders/, and plug-in scan-cache INIs "
            "(reaper-*plugins*.ini, reaper-jsfx.ini, reaper-clap-*.ini, reaper-recentfx.ini); "
            "use --full-resource-mirror or --comprehensive to match export-audit disk coverage."
        )
    if lean.include_host_cache:
        lines.append(
            "Host cache: ~/Library/Caches/com.cockos.reaper included (optional tier; matches dump host_cache)."
        )
    else:
        lines.append(
            "Host cache: not included (use --include-host-cache or --comprehensive)."
        )
    lines.append(
        "Audio: user plug-ins under ~/Library/Audio/Plug-Ins; user AU/Vendor presets under ~/Library/Audio/Presets."
    )
    if cfg.include_system_plugins:
        lines.append("System plug-ins: /Library/Audio/Plug-Ins included.")
    if cfg.include_system_audio_presets:
        lines.append("System Audio/Presets: /Library/Audio/Presets included.")
    if cfg.official_export_zip:
        lines.append(
            "Cockos Export configuration zip stored as artifact (compare with config-inspect; not auto-merged on restore)."
        )
    lines.append(
        "Projects: paths from reaper.ini + --project-root/--extra-root; absolute paths may need restore --map-user."
    )
    return lines


def run_backup(cfg: BackupConfig) -> dict:
    log = make_log(cfg.verbose)
    if cfg.comprehensive:
        cfg.lean = LeanOptions(
            include_plugin_scan_caches=True,
            include_metadata_caches=True,
            include_queued_renders=True,
            include_host_cache=True,
            include_peaks=cfg.lean.include_peaks,
            exclude_project_backups=cfg.lean.exclude_project_backups,
            full_resource_mirror=True,
            include_os_metadata=cfg.lean.include_os_metadata,
        )
        log(
            "backup: comprehensive profile — full REAPER resource tree, host cache, "
            "metadata/queued/scan INIs (aligned with export-audit / preset-details coverage)"
        )
    log(
        f"backup: starting (dry_run={cfg.dry_run}) → output {cfg.output.resolve()}"
    )

    home_path = _home(cfg)
    if cfg.resource_path:
        resource = cfg.resource_path.expanduser().resolve()
    else:
        resource = paths.resolve_resource_path(None, home_dir=home_path)
    data_root = (cfg.output / "data").resolve()
    manifest_entries: list[dict] = []

    ini = parse_reaper_ini(resource / "reaper.ini")
    merged_project_roots = _merge_project_roots(cfg, ini)
    log(f"backup: resource path {resource}")

    # --- REAPER.app ---
    app_src = (cfg.reaper_app_path or paths.default_reaper_app()).expanduser()
    if cfg.include_reaper_app and app_src.exists():
        log("backup: copying REAPER.app …")
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
        log("backup: walking Application Support/REAPER (resource) …")
        dest_base = data_root / "resource"
        res_n = 0
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
                res_n += 1
                if res_n % 2500 == 0:
                    log(f"backup: … {res_n} files in resource tree so far")
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
    log("backup: com.cockos.reaper.plist …")
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
        phase_label: str,
    ) -> None:
        if not src_root.is_dir():
            return
        log(f"backup: {phase_label} …")
        dest_data_base = data_root / data_rel_prefix
        nf = 0
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
                nf += 1
                if nf % 2500 == 0:
                    log(f"backup: … {nf} files in {phase_label} so far")
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
            phase_label="host cache",
        )

    # --- plugins user ---
    _walk_layer(
        _home(cfg) / "Library" / "Audio" / "Plug-Ins",
        Path("plugins_user") / "Library" / "Audio" / "Plug-Ins",
        "plugins_user",
        "Library/Audio/Plug-Ins",
        dest_is_root=False,
        use_project_skip=False,
        phase_label="Audio/Plug-Ins (user)",
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
            phase_label="Audio/Plug-Ins (system)",
        )

    # --- audio presets user ---
    _walk_layer(
        _home(cfg) / "Library" / "Audio" / "Presets",
        Path("audio_presets_user") / "Library" / "Audio" / "Presets",
        "audio_presets_user",
        "Library/Audio/Presets",
        dest_is_root=False,
        use_project_skip=False,
        phase_label="Audio/Presets (user)",
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
            phase_label="Audio/Presets (system)",
        )

    # --- project trees ---
    log("backup: project/media trees from reaper.ini and --project-root …")
    seen_roots: set[str] = set()
    for root in merged_project_roots:
        r = root.expanduser().resolve()
        key = str(r)
        if key in seen_roots or not r.is_dir():
            continue
        seen_roots.add(key)
        log(f"backup: project root {r} …")
        slug = hashlib.sha256(key.encode()).hexdigest()[:12]
        dest_prefix = data_root / "projects" / slug
        pj_n = 0
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
                pj_n += 1
                if pj_n % 2500 == 0:
                    log(
                        f"backup: … {pj_n} files from this project root so far"
                    )
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
        log("backup: Cockos export configuration zip …")
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
        "backup_profile": "comprehensive" if cfg.comprehensive else "lean",
        "path_hints": extract_path_hints(ini),
        "coverage_notes": _coverage_notes(cfg),
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
        log("backup: writing manifest.json …")
        cfg.output.mkdir(parents=True, exist_ok=True)
        man_path = cfg.output / "manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    else:
        log(
            f"backup: dry-run — would write {len(manifest.get('entries', []))} manifest entries"
        )

    log("backup: done")
    return manifest
