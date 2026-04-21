"""CLI entry point for reaper-backup."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backup import BackupConfig, run_backup
from .config_zip import compare_zip_to_paths, list_zip_members
from .dump_lib import resource_relative_set, run_dump
from .export_audit import format_evidence_text, run_export_audit
from .lean import LeanOptions
from .audio_inspect import run_audio_inspect
from .preset_inventory import run_preset_details
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
        verbose=not args.quiet,
        preset_details=args.preset_details,
        include_audio_presets_in_preset_details=not args.no_audio_presets_in_preset_details,
        preset_details_max_files=args.preset_details_max_files,
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
        if args.preset_details and "preset_details" in payload:
            pd = payload["preset_details"]
            rr = pd.get("reaper_resource_presets") or {}
            er = pd.get("reaper_effects_rpl") or {}
            ap = pd.get("audio_presets_user") or {}
            print(
                "preset_details: presets/",
                rr.get("file_count"),
                "files; Effects/*.rpl",
                er.get("file_count"),
                "files; Audio/Presets",
                ap.get("file_count"),
                "files (see JSON for per-file metadata)",
            )
    return 0


def _audio_inspect_cmd(args: argparse.Namespace) -> int:
    payload = run_audio_inspect(
        include_system_plug_ins=args.include_system_plug_ins,
        include_system_presets=args.include_system_presets,
        include_audio_presets=not args.no_audio_presets,
        max_preset_files=args.max_files,
    )
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        pu = payload.get("plug_ins_user") or {}
        print("Plug-Ins (user):", pu.get("bundle_count"), "bundles at", pu.get("root"))
        if pu.get("by_format"):
            print("  by format:", pu.get("by_format"))
        if payload.get("plug_ins_system"):
            ps = payload["plug_ins_system"]
            print("Plug-Ins (system):", ps.get("bundle_count"), "bundles at", ps.get("root"))
            if ps.get("by_format"):
                print("  by format:", ps.get("by_format"))
        ap = payload.get("audio_presets_user") or {}
        if ap.get("skipped"):
            print("Audio/Presets:", ap.get("reason", "skipped"))
        else:
            print(
                "Audio/Presets (user):",
                ap.get("file_count"),
                "files",
                "(truncated)" if ap.get("truncated") else "",
            )
            if ap.get("by_extension"):
                print("  by extension:", ap["by_extension"])
        if payload.get("audio_presets_system"):
            aps = payload["audio_presets_system"]
            print(
                "Audio/Presets (system):",
                aps.get("file_count"),
                "files",
                "(truncated)" if aps.get("truncated") else "",
            )
        print(payload.get("reaper_resource_note", ""))
    return 0


def _preset_details_cmd(args: argparse.Namespace) -> int:
    payload = run_preset_details(
        resource_path=Path(args.resource).expanduser() if args.resource else None,
        include_audio_presets_user=not args.no_audio_presets,
        max_files_per_tree=args.max_files,
    )
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        rr = payload.get("reaper_resource_presets") or {}
        er = payload.get("reaper_effects_rpl") or {}
        ap = payload.get("audio_presets_user") or {}
        print("resource_path:", payload.get("resource_path"))
        st = payload.get("resource_path_status") or {}
        if st:
            print(
                "resource_path_status:",
                "dir" if st.get("resource_dir_exists") else "missing",
                "| reaper.ini",
                "yes" if st.get("reaper_ini_present") else "no",
            )
        for line in payload.get("empty_scan_hints") or ():
            print("hint:", line)
        print("REAPER presets/:", rr.get("file_count"), "files", "(truncated)" if rr.get("truncated") else "")
        if rr.get("by_extension"):
            print("  by extension:", rr["by_extension"])
        if rr.get("by_first_path_component_under_presets"):
            print("  by plugin folder (first level):", rr["by_first_path_component_under_presets"])
        print(
            "Effects/*.rpl:",
            er.get("file_count"),
            "files",
            "(truncated)" if er.get("truncated") else "",
        )
        if er.get("by_author_folder"):
            print("  by author folder:", er["by_author_folder"])
        if er.get("note"):
            print(" ", er["note"])
        if ap.get("skipped"):
            print("Audio/Presets: (skipped —", ap.get("reason", "disabled"), ")")
        else:
            print("Audio/Presets:", ap.get("file_count"), "files", "(truncated)" if ap.get("truncated") else "")
            if ap.get("by_extension"):
                print("  by extension:", ap["by_extension"])
        print("(Use --format json for full per-file details: sections, size, mtime, …)")
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
        comprehensive=args.comprehensive,
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
        verbose=not args.quiet,
    )
    manifest = run_backup(cfg)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "backup_profile": manifest.get("backup_profile"),
                    "entry_count": len(manifest.get("entries", [])),
                },
                indent=2,
            )
        )
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
        home_dir=Path(args.home).expanduser() if args.home else None,
        verbose=not args.quiet,
    )
    log = run_restore(cfg)
    for row in log:
        print(json.dumps(row))
    return 0


def _export_audit_cmd(args: argparse.Namespace) -> int:
    rpp_limit = None if args.all_rpp else args.rpp_max_files
    payload = run_export_audit(
        resource_path=Path(args.resource).expanduser() if args.resource else None,
        extra_roots=[Path(p) for p in (args.extra_root or [])],
        project_roots=[Path(p) for p in (args.project_root or [])],
        scan_rpp=not args.no_rpp,
        rpp_max_files=rpp_limit,
        verbose=not args.quiet,
    )
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print("resource_path:", payload.get("resource_path"))
        print("RPP files discovered:", payload.get("rpp_files_discovered"))
        for line in payload.get("recommendations", []):
            print("-", line)
        js = payload.get("jsfx", {})
        proj = js.get("projects", {})
        print(
            "JSFX: Effects dir files:",
            js.get("user_effects_dir", {}).get("file_count", 0),
            "| projects with <JS (in scan):",
            proj.get("rpp_projects_with_jsfx", proj.get("rpp_files_with_jsfx", 0)),
        )
        scan = payload.get("rpp_jsfx_scan", {})
        if scan.get("capped"):
            print(
                "  (JSFX scan capped:",
                scan.get("scanned"),
                "of",
                payload.get("rpp_files_discovered"),
                ".rpp — use --all-rpp for full history)",
            )
        print()
        print(format_evidence_text(payload))
    return 0


def _config_inspect_cmd(args: argparse.Namespace) -> int:
    from .progress import stderr_line

    log = stderr_line if not args.quiet else lambda _m: None
    z = Path(args.zip_path).expanduser()
    log(f"config-inspect: reading zip {z} …")
    members = list_zip_members(z)
    total = sum(s for _, s in members)
    log(f"config-inspect: {len(members)} member(s), {total} bytes (uncompressed)")
    print(f"{z}: {len(members)} files, {total} bytes (uncompressed)")
    if not args.summary_only:
        show = members if args.list else members[: args.preview]
        if args.list:
            log("config-inspect: listing all members to stdout …")
        else:
            log(
                f"config-inspect: listing first {len(show)} of {len(members)} members …"
            )
        print()
        print(f"{'size (bytes)':>12}  path")
        for name, sz in show:
            print(f"{sz:12d}  {name}")
        if not args.list and len(members) > len(show):
            more = len(members) - len(show)
            print(f"... {more} more file(s); re-run with --list for the full listing")
    if args.compare_with:
        dump_path = Path(args.compare_with).expanduser()
        log(f"config-inspect: loading {dump_path} for compare …")
        dump = json.loads(dump_path.read_text(encoding="utf-8"))
        rel = resource_relative_set(dump)
        log("config-inspect: comparing zip paths to dump resource paths …")
        diff = compare_zip_to_paths(z, rel)
        print(json.dumps(diff, indent=2))
    log("config-inspect: done")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reaper-backup", description="REAPER backup / restore helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    quiet_parent = argparse.ArgumentParser(add_help=False)
    quiet_parent.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages on stderr (keep stdout for JSON / piping)",
    )

    d = sub.add_parser(
        "dump",
        parents=[quiet_parent],
        help="Discover REAPER paths and inventory (read-only)",
    )
    d.add_argument("--resource", help="Override REAPER resource path")
    d.add_argument("--extra-root", action="append", help="Extra directory roots (repeatable)")
    d.add_argument("--project-root", action="append", help="Extra project/media roots")
    d.add_argument("--rpp-details", action="store_true", help="Parse sample of .rpp files")
    d.add_argument("--rpp-limit", type=int, default=50)
    d.add_argument(
        "--preset-details",
        action="store_true",
        help="Deep preset inventory: content sniff, INI sections, path-derived plugin hints",
    )
    d.add_argument(
        "--no-audio-presets-in-preset-details",
        action="store_true",
        help="With --preset-details, skip ~/Library/Audio/Presets",
    )
    d.add_argument(
        "--preset-details-max-files",
        type=int,
        default=10_000,
        metavar="N",
        help="Cap files analyzed per tree (default 10000)",
    )
    d.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format",
    )
    d.set_defaults(func=_dump_cmd)

    pd = sub.add_parser(
        "preset-details",
        parents=[quiet_parent],
        help="Preset-focused report: presets/, Effects/*.rpl, Audio/Presets (metadata, not just names)",
    )
    pd.add_argument("--resource", help="Override REAPER resource path")
    pd.add_argument(
        "--no-audio-presets",
        action="store_true",
        help="Skip ~/Library/Audio/Presets (still scans presets/ and Effects/*.rpl)",
    )
    pd.add_argument(
        "--max-files",
        type=int,
        default=10_000,
        metavar="N",
        help="Max files per tree (default 10000)",
    )
    pd.add_argument("--format", choices=("json", "text"), default="json")
    pd.set_defaults(func=_preset_details_cmd)

    ai = sub.add_parser(
        "audio-inspect",
        parents=[quiet_parent],
        help="~/Library/Audio/Plug-Ins + Audio/Presets: bundles and preset file details (no full dump)",
    )
    ai.add_argument(
        "--include-system-plug-ins",
        action="store_true",
        help="Also scan /Library/Audio/Plug-Ins",
    )
    ai.add_argument(
        "--include-system-presets",
        action="store_true",
        help="Also deep-scan /Library/Audio/Presets",
    )
    ai.add_argument(
        "--no-audio-presets",
        action="store_true",
        help="Only list plug-in bundles; skip ~/Library/Audio/Presets file walk",
    )
    ai.add_argument(
        "--max-files",
        type=int,
        default=10_000,
        metavar="N",
        help="Cap preset files analyzed per tree (default 10000)",
    )
    ai.add_argument("--format", choices=("json", "text"), default="json")
    ai.set_defaults(func=_audio_inspect_cmd)

    b = sub.add_parser(
        "backup",
        parents=[quiet_parent],
        help="Create lean backup directory + manifest.json",
    )
    b.add_argument("--output", required=True, help="Output directory")
    b.add_argument(
        "--comprehensive",
        action="store_true",
        help="Full REAPER resource mirror + host cache + caches/queues/scan INIs (matches export-audit disk scope; still add --official-export zip separately)",
    )
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

    r = sub.add_parser(
        "restore",
        parents=[quiet_parent],
        help="Restore from backup directory (canonical order)",
    )
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
    r.add_argument(
        "--home",
        default=None,
        help="Destination home directory for restore (default: current user's ~)",
    )
    r.set_defaults(func=_restore_cmd)

    e = sub.add_parser(
        "export-audit",
        parents=[quiet_parent],
        help="Audit live resource path for Cockos Export configuration checkboxes (no zip needed)",
    )
    e.add_argument("--resource", help="Override REAPER resource path")
    e.add_argument("--extra-root", action="append", help="Extra roots for finding .rpp (repeatable)")
    e.add_argument("--project-root", action="append", help="Extra project roots for .rpp scan")
    e.add_argument(
        "--no-rpp",
        action="store_true",
        help="Do not scan .rpp files for JSFX (<JS lines); faster",
    )
    e.add_argument(
        "--all-rpp",
        action="store_true",
        help="Scan every discovered .rpp for JSFX (no cap; use for full project history)",
    )
    e.add_argument(
        "--rpp-max-files",
        type=int,
        default=150,
        metavar="N",
        help="Max .rpp files to read for JSFX when not using --all-rpp (default 150)",
    )
    e.add_argument("--format", choices=("json", "text"), default="json")
    e.set_defaults(func=_export_audit_cmd)

    c = sub.add_parser(
        "config-inspect",
        parents=[quiet_parent],
        help="Inspect Cockos Export configuration zip",
    )
    c.add_argument("zip_path", help="Path to exported zip")
    c.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print the one-line summary (no member table)",
    )
    c.add_argument(
        "--preview",
        type=int,
        default=40,
        metavar="N",
        help="When not using --list, show first N members (default 40)",
    )
    c.add_argument(
        "--list",
        action="store_true",
        help="Print every member path and size (overrides --preview)",
    )
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
