"""CLI entry point for reaper-backup."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backup import BackupConfig, run_backup
from .config_zip import compare_zip_to_paths, list_zip_members
from .dump_lib import resource_relative_set, run_dump
from .lean import LeanOptions
from .restore import RestoreConfig, run_restore


def _dump_cmd(args: argparse.Namespace) -> int:
    extra = [Path(p) for p in (args.extra_root or [])]
    proj = [Path(p) for p in (args.project_root or [])]
    rp = Path(args.resource).expanduser() if args.resource else None
    payload = run_dump(
        resource_path=rp,
        project_roots=proj,
        extra_roots=extra,
        rpp_details=args.rpp_details,
        rpp_limit=args.rpp_limit,
    )
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print("resource_path:", payload.get("resource_path"))
        print("reaper_plist:", payload.get("reaper_plist"))
        print("resource file count:", len(payload.get("resource_files", [])))
        print("plugins (fs):", len(payload.get("plugins_fs", [])))
        print("project roots checked:", len(payload.get("project_roots_checked", [])))
        print("RPP paths:", len(payload.get("rpp_files", [])))
        if args.rpp_details and "rpp_details" in payload:
            for row in payload["rpp_details"][:20]:
                print(" ", row.get("path"), row.get("track_count"), row.get("reaper_version"))
    return 0


def _backup_cmd(args: argparse.Namespace) -> int:
    lean = LeanOptions(
        include_plugin_scan_caches=args.include_plugin_scan_caches,
        include_metadata_caches=args.include_metadata_caches,
        include_queued_renders=args.include_queued_renders,
        include_host_cache=args.include_host_cache,
        include_peaks=args.include_peaks,
        exclude_project_backups=args.exclude_project_backups,
        full_resource_mirror=args.full_resource_mirror,
        include_os_metadata=args.include_os_metadata,
    )
    cfg = BackupConfig(
        output=Path(args.output).expanduser(),
        resource_path=Path(args.resource).expanduser() if args.resource else None,
        lean=lean,
        extra_roots=[Path(p) for p in (args.extra_root or [])],
        project_roots=[Path(p) for p in (args.project_root or [])],
        include_system_plugins=args.include_system_plugins,
        include_system_audio_presets=args.include_system_audio_presets,
        official_export_zip=Path(args.official_export).expanduser()
        if args.official_export
        else None,
        include_reaper_app=args.include_reaper_app,
        reaper_app_path=Path(args.reaper_app).expanduser()
        if args.reaper_app
        else None,
        checksums=args.checksum,
        dry_run=args.dry_run,
    )
    manifest = run_backup(cfg)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "entry_count": len(manifest.get("entries", []))}, indent=2))
    else:
        print("Wrote", cfg.output / "manifest.json")
    return 0


def _restore_cmd(args: argparse.Namespace) -> int:
    root = Path(args.from_dir).expanduser()
    map_user = None
    if args.map_user:
        if "=" not in args.map_user:
            print("--map-user must be OLD=NEW", file=sys.stderr)
            return 2
        a, b = args.map_user.split("=", 1)
        map_user = (a, b)
    cfg = RestoreConfig(
        backup_root=root,
        dry_run=args.dry_run,
        map_user=map_user,
    )
    log = run_restore(cfg)
    for row in log:
        print(json.dumps(row))
    return 0


def _config_inspect_cmd(args: argparse.Namespace) -> int:
    z = Path(args.zip_path).expanduser()
    members = list_zip_members(z)
    total = sum(s for _, s in members)
    print(f"{z}: {len(members)} files, {total} bytes (uncompressed)")
    if args.list:
        for name, sz in members:
            print(f"  {sz:10d}  {name}")
    if args.compare_with:
        dump_path = Path(args.compare_with).expanduser()
        dump = json.loads(dump_path.read_text(encoding="utf-8"))
        rel = resource_relative_set(dump)
        diff = compare_zip_to_paths(z, rel)
        print(json.dumps(diff, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reaper-backup", description="REAPER backup / restore helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", help="Discover REAPER paths and inventory (read-only)")
    d.add_argument("--resource", help="Override REAPER resource path")
    d.add_argument("--extra-root", action="append", help="Extra directory roots (repeatable)")
    d.add_argument("--project-root", action="append", help="Extra project/media roots")
    d.add_argument("--rpp-details", action="store_true", help="Parse sample of .rpp files")
    d.add_argument("--rpp-limit", type=int, default=50)
    d.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format",
    )
    d.set_defaults(func=_dump_cmd)

    b = sub.add_parser("backup", help="Create lean backup directory + manifest.json")
    b.add_argument("--output", required=True, help="Output directory")
    b.add_argument("--resource", help="Override REAPER resource path")
    b.add_argument("--extra-root", action="append", help="Include this tree (vendor/media)")
    b.add_argument("--project-root", action="append", help="Extra project root to back up")
    b.add_argument("--official-export", help="Path to Cockos Export configuration zip")
    b.add_argument("--include-system-plugins", action="store_true")
    b.add_argument("--include-system-audio-presets", action="store_true")
    b.add_argument("--include-reaper-app", action="store_true")
    b.add_argument("--reaper-app", help="Path to REAPER.app (default /Applications/REAPER.app)")
    b.add_argument("--checksum", action="store_true", help="SHA-256 per file")
    b.add_argument("--dry-run", action="store_true", help="Do not write files; print summary")
    b.add_argument("--include-plugin-scan-caches", action="store_true")
    b.add_argument("--include-metadata-caches", action="store_true")
    b.add_argument("--include-queued-renders", action="store_true")
    b.add_argument("--include-host-cache", action="store_true")
    b.add_argument("--include-peaks", action="store_true")
    b.add_argument("--exclude-project-backups", action="store_true")
    b.add_argument("--full-resource-mirror", action="store_true")
    b.add_argument("--include-os-metadata", action="store_true")
    b.set_defaults(func=_backup_cmd)

    r = sub.add_parser("restore", help="Restore from backup directory (canonical order)")
    r.add_argument(
        "--from",
        dest="from_dir",
        required=True,
        help="Backup directory containing manifest.json",
    )
    r.add_argument("--dry-run", action="store_true")
    r.add_argument(
        "--map-user",
        help="Remap home for absolute paths: OLD_HOME=NEW_HOME",
    )
    r.set_defaults(func=_restore_cmd)

    c = sub.add_parser("config-inspect", help="Inspect Cockos Export configuration zip")
    c.add_argument("zip_path", help="Path to exported zip")
    c.add_argument("--list", action="store_true", help="Print all member paths and sizes")
    c.add_argument(
        "--compare-with",
        metavar="DUMP.json",
        help="Compare zip members to paths from a dump JSON",
    )
    c.set_defaults(func=_config_inspect_cmd)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
