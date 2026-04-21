"""
Heuristic audit of the live REAPER resource path for what Cockos
"Export configuration" categories likely apply to — without needing a zip first.

This is filesystem + optional .rpp scan for `<JS` lines (JSFX in projects). By default only
the first N projects are read (speed); use ``rpp_max_files=None`` / CLI ``--all-rpp`` to scan
every discovered .rpp. REAPER's exact export bundle may differ slightly.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from .dump_lib import collect_project_paths
from .paths import default_resource_path
from .progress import find_rpp_files_with_progress, make_log
from .reaper_ini import parse_reaper_ini

_JS_LINE = re.compile(r"^\s+<JS\s+", re.MULTILINE)


def _tree_metrics(root: Path) -> dict:
    if not root.is_dir():
        return {"present": False, "file_count": 0, "total_bytes": 0}
    n, total = 0, 0
    for dirpath, _dn, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                total += p.stat().st_size
                n += 1
            except OSError:
                pass
    return {"present": True, "file_count": n, "total_bytes": total}


def _root_ini_names(resource: Path, *, limit: int = 80) -> list[str]:
    if not resource.is_dir():
        return []
    names: list[str] = []
    for p in sorted(resource.iterdir()):
        if p.is_file() and p.suffix.lower() == ".ini":
            names.append(p.name)
    return names[:limit]


def _glob_any(resource: Path, pattern: str) -> list[Path]:
    return list(resource.glob(pattern)) if resource.is_dir() else []


def _count_root_patterns(resource: Path, globs: tuple[str, ...]) -> dict:
    out: dict[str, list[str]] = {}
    for g in globs:
        hits = [p.name for p in _glob_any(resource, g)]
        if hits:
            out[g] = sorted(hits)
    return out


def scan_rpp_for_jsfx(
    rpp_paths: list[Path],
    *,
    max_files: int | None = 150,
    max_bytes_per_file: int = 4_000_000,
    log: Callable[[str], None] | None = None,
    read_progress_interval: int = 50,
) -> dict:
    """
    Read project files for `<JS` FX lines (JSFX instances). If ``max_files`` is ``None``,
    every path in ``rpp_paths`` is scanned (full history under discovered roots).
    """
    eligible = len(rpp_paths)
    seen_files = 0
    projects_with_jsfx = 0
    examples: list[dict] = []
    limit_note = f" (max {max_files} files)" if max_files is not None else " (all files)"
    if log:
        log(
            f"export-audit: scanning {eligible} .rpp file(s) for JSFX <JS lines{limit_note} …"
        )

    for rpp in rpp_paths:
        if max_files is not None and seen_files >= max_files:
            break
        try:
            raw = rpp.read_bytes()
        except OSError:
            continue
        if len(raw) > max_bytes_per_file:
            raw = raw[:max_bytes_per_file]
        text = raw.decode("utf-8", errors="replace")
        seen_files += 1
        if log and seen_files % read_progress_interval == 0:
            target = (
                min(max_files, eligible) if max_files is not None else eligible
            )
            log(
                f"export-audit: … read {seen_files}/{target} .rpp for JSFX "
                f"({projects_with_jsfx} project(s) with <JS so far)"
            )
        if not _JS_LINE.search(text):
            continue
        projects_with_jsfx += 1
        if len(examples) < 8:
            m = _JS_LINE.search(text)
            line_excerpt = ""
            if m:
                start = m.start()
                line_excerpt = text[start : start + 120].splitlines()[0][:200]
            examples.append(
                {
                    "project": str(rpp.resolve()),
                    "sample_line": line_excerpt,
                }
            )

    capped = max_files is not None and eligible > seen_files

    if log:
        log(
            f"export-audit: JSFX scan done — read {seen_files} .rpp, "
            f"{projects_with_jsfx} project(s) contain <JS lines"
        )

    return {
        "rpp_files_eligible": eligible,
        "rpp_files_scanned": seen_files,
        "jsfx_scan_capped": capped,
        "jsfx_scan_limit": max_files,
        "rpp_projects_with_jsfx": projects_with_jsfx,
        # legacy key (count of projects containing <JS, not "files")
        "rpp_files_with_jsfx": projects_with_jsfx,
        "examples": examples,
    }


def run_export_audit(
    *,
    resource_path: Path | None = None,
    extra_roots: list[Path] | None = None,
    project_roots: list[Path] | None = None,
    scan_rpp: bool = True,
    rpp_max_files: int | None = 150,
    verbose: bool = True,
) -> dict:
    """
    Build JSON-serializable audit: per-category signals and include recommendations.
    """
    log = make_log(verbose)

    resource_path = resource_path or default_resource_path()
    extra_roots = extra_roots or []
    project_roots = project_roots or []

    log(f"export-audit: resource path {resource_path.resolve()}")

    ini_path = resource_path / "reaper.ini"
    ini = parse_reaper_ini(ini_path)
    merged_roots = list(project_roots) + collect_project_paths(ini, extra_roots)
    log(
        f"export-audit: {len(merged_roots)} project root(s) to search "
        f"(from reaper.ini + --project-root / --extra-root)"
    )

    if scan_rpp:
        rpp_list = find_rpp_files_with_progress(
            merged_roots, log=log, prefix="export-audit"
        )
        log(f"export-audit: discovery complete — {len(rpp_list)} .rpp file(s) total")
    else:
        rpp_list = []

    log(
        "export-audit: measuring resource folders for Cockos export categories "
        "(large folders like Data/ can take a while) …"
    )

    # Directory-backed categories (Cockos dialog names → subdirs / patterns)
    categories: dict[str, dict] = {}

    def add_cat(
        key: str,
        *,
        label: str,
        metrics: dict,
        suggest: bool | None = None,
        notes: str = "",
    ) -> None:
        row = {
            "cockos_label": label,
            "metrics": metrics,
            "suggest_include": suggest
            if suggest is not None
            else (metrics.get("file_count", 0) > 0),
            "notes": notes,
        }
        categories[key] = row

    # Configuration: core inis at resource root (what "Configuration" tick usually covers)
    root_inis = _root_ini_names(resource_path)
    add_cat(
        "configuration",
        label="Configuration",
        metrics={
            "reaper_ini_present": ini_path.is_file(),
            "root_ini_count": len(
                [x for x in (resource_path.iterdir() if resource_path.is_dir() else []) if x.is_file() and x.suffix.lower() == ".ini"]
            ),
            "root_ini_names_sample": root_inis[:40],
        },
        suggest=True,
        notes="Core preferences and many top-level .ini files.",
    )

    pt = _tree_metrics(resource_path / "ProjectTemplates")
    tt = _tree_metrics(resource_path / "TrackTemplates")
    merge_files = pt["file_count"] + tt["file_count"]
    merge_bytes = pt["total_bytes"] + tt["total_bytes"]
    add_cat(
        "project_and_track_templates",
        label="Project and track templates",
        metrics={
            "ProjectTemplates": pt,
            "TrackTemplates": tt,
            "combined_file_count": merge_files,
            "combined_total_bytes": merge_bytes,
        },
        suggest=merge_files > 0,
    )

    for key, lbl, subpath in (
        ("plugin_presets", "Plug-in presets", resource_path / "presets"),
        ("fx_chains", "FX chains", resource_path / "FXChains"),
        ("reascripts", "ReaScripts", resource_path / "Scripts"),
        ("color_themes", "Color themes", resource_path / "ColorThemes"),
        ("js_fx", "JS FX", resource_path / "Effects"),
        ("misc_data", "Misc data", resource_path / "Data"),
        ("language_packs", "Language Packs", resource_path / "LangPack"),
        ("automation_items", "Automation Items", resource_path / "AutomationItems"),
        ("midi_note_cc_names", "MIDI Note/CC Names", resource_path / "MIDINoteNames"),
        ("media_explorer", "Media Explorer Databases", resource_path / "MediaExplorer"),
    ):
        if key == "misc_data":
            log(f"export-audit: walking {subpath.name}/ (often the slowest folder) …")
        add_cat(key, label=lbl, metrics=_tree_metrics(subpath))

    # Cursors + key maps (two dirs)
    cur = _tree_metrics(resource_path / "Cursors")
    km = _tree_metrics(resource_path / "KeyMaps")
    add_cat(
        "cursors_and_key_maps",
        label="Cursors and key maps",
        metrics={"Cursors": cur, "KeyMaps": km},
        suggest=(cur["file_count"] + km["file_count"]) > 0,
    )

    # Menus / toolbars / actions — mostly root inis + KeyMaps already counted
    menu_hits = _count_root_patterns(
        resource_path,
        ("reaper-menu*.ini", "reaper-main_menu.ini", "reaper-toolbar*.ini"),
    )
    add_cat(
        "menus_and_toolbars",
        label="Menus and toolbars",
        metrics={"root_ini_matches": menu_hits},
        suggest=bool(menu_hits),
        notes="Looks for reaper-menu*.ini, reaper-main_menu.ini, reaper-toolbar*.ini at resource root.",
    )

    keymap_files = (
        list((resource_path / "KeyMaps").glob("*.ReaperKeyMap"))
        if (resource_path / "KeyMaps").is_dir()
        else []
    )
    add_cat(
        "actions_and_key_bindings",
        label="Actions and key bindings",
        metrics={
            "ReaperKeyMap_files": len(keymap_files),
            "sample": [p.name for p in keymap_files[:12]],
        },
        suggest=len(keymap_files) > 0,
        notes="Counts *.ReaperKeyMap under KeyMaps/.",
    )

    # Menu sets / channel mappings — best-effort names
    ms = _tree_metrics(resource_path / "MenuSets")
    add_cat(
        "menu_sets",
        label="Menu sets",
        metrics=ms,
        suggest=ms["file_count"] > 0,
    )

    ch = _count_root_patterns(resource_path, ("reaper_chan*.ini", "*chanmap*"))
    ch_dir = _tree_metrics(resource_path / "ChanMap")
    add_cat(
        "channel_mappings",
        label="Channel mappings",
        metrics={"root_glob_hits": ch, "ChanMap_dir": ch_dir},
        suggest=bool(ch) or ch_dir["file_count"] > 0,
        notes="Heuristic: ChanMap/ or reaper_chan*.ini at root.",
    )

    # Web interface — custom pages sometimes under reaper_www/
    www_path = resource_path / "reaper_www"
    www = (
        _tree_metrics(www_path)
        if www_path.is_dir()
        else {"present": False, "file_count": 0, "total_bytes": 0}
    )
    osc_m = _tree_metrics(resource_path / "OSC")
    add_cat(
        "web_interface_pages",
        label="Web Interface Pages",
        metrics={"reaper_www": www, "OSC": osc_m},
        suggest=www["file_count"] > 0,
        notes="Custom web pages may live under reaper_www/ if present; otherwise unclear from files alone.",
    )

    # Unsaved / cached — MetadataCaches (discourage for export parity; regenerable)
    meta = _tree_metrics(resource_path / "MetadataCaches")
    add_cat(
        "unsaved_cached_metadata",
        label="Unsaved/Cached Metadata",
        metrics=meta,
        suggest=False,
        notes="Usually skip for migration: regenerable; tick only if you know you need it.",
    )

    log("export-audit: category pass finished")

    jsfx_rpp = (
        scan_rpp_for_jsfx(
            rpp_list,
            max_files=rpp_max_files,
            log=log if scan_rpp else None,
        )
        if scan_rpp
        else {}
    )

    # Aggregate JSFX: user Effects/ tree + project usage
    jsfx_dir = categories.get("js_fx", {}).get("metrics", {})
    jsfx_signal = {
        "user_effects_dir": jsfx_dir,
        "projects": jsfx_rpp,
        "interpretation": (
            "If Effects/ is non-empty or any scanned project contains <JS lines, "
            "you likely use JSFX somewhere — tick JS FX in Export configuration."
        ),
    }

    recommendations: list[str] = []
    for cid, row in categories.items():
        if cid == "unsaved_cached_metadata":
            continue
        if row.get("suggest_include"):
            recommendations.append(
                f"Include “{row['cockos_label']}”: on-disk signals present."
            )
    if not recommendations:
        recommendations.append(
            "At minimum include Configuration; other categories show little or no custom data."
        )

    if jsfx_rpp.get("rpp_projects_with_jsfx", jsfx_rpp.get("rpp_files_with_jsfx", 0)) > 0 and not (
        jsfx_dir.get("file_count", 0) > 0
    ):
        recommendations.append(
            "JSFX appears in scanned projects but Effects/ is empty — stock JSFX in REAPER.app "
            "still counts as usage; tick JS FX to carry presets/chains tied to JS."
        )

    if jsfx_rpp.get("jsfx_scan_capped"):
        recommendations.append(
            f"JSFX project scan stopped after {jsfx_rpp.get('rpp_files_scanned', 0)} of "
            f"{jsfx_rpp.get('rpp_files_eligible', 0)} .rpp files — re-run with "
            "`reaper-backup export-audit --all-rpp` to check your full project history."
        )

    log("export-audit: done")

    return {
        "resource_path": str(resource_path.resolve()),
        "methodology": (
            "Heuristic audit of your live resource folder (and optional .rpp scan). "
            "Compare with Cockos Export configuration dialog; use config-inspect on the zip afterward."
        ),
        "categories": categories,
        "jsfx": jsfx_signal,
        "recommendations": recommendations,
        "rpp_files_discovered": len(rpp_list),
        "rpp_jsfx_scan": {
            "eligible_rpp_files": len(rpp_list),
            "scanned": jsfx_rpp.get("rpp_files_scanned") if scan_rpp else 0,
            "limit": jsfx_rpp.get("jsfx_scan_limit") if scan_rpp else None,
            "capped": jsfx_rpp.get("jsfx_scan_capped") if scan_rpp else False,
        },
    }
