"""
Rich inventory of REAPER preset-related files: presets/, Effects/*.rpl, and optional Audio/Presets.

Goes beyond filenames: path-derived plugin hints, INI sections, size/mtime, content kind.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import paths

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$", re.MULTILINE)
_MAX_READ = 256 * 1024


def _infer_from_relative(rel: str) -> dict:
    """Best-effort identity from resource-relative path (presets/, Effects/, Audio/Presets/)."""
    r = rel.replace("\\", "/")
    parts_full = r.split("/")
    out: dict = {"path_segments": parts_full}

    if r.startswith("Audio/Presets/"):
        rest = r[len("Audio/Presets/") :].split("/")
        out["tree"] = "audio_presets_user"
        out["audio_presets_vendor_folder"] = rest[0] if rest else None
        out["inferred_fx_format"] = None
        out["inferred_vendor_or_plugin"] = None
        return out

    if len(parts_full) >= 2 and parts_full[0] == "Effects":
        out["tree"] = "reaper_effects_rpl"
        out["effects_author_folder"] = (
            parts_full[1] if len(parts_full) >= 3 else None
        )
        out["inferred_fx_format"] = None
        out["inferred_vendor_or_plugin"] = None
        return out

    parts = parts_full[:]
    if parts and parts[0] == "presets":
        parts = parts[1:]
    out["tree"] = "reaper_resource_presets"
    if not parts:
        return out
    head = parts[0]
    upper = head.upper()
    fx = None
    for tag in ("VST3", "VST2", "VST", "AU", "JS", "CLAP"):
        if upper.startswith(tag):
            fx = tag
            break
    if fx:
        rest = head[len(fx) :].lstrip(" -_:\t")
        out["inferred_fx_format"] = fx
        out["inferred_vendor_or_plugin"] = rest.strip() if rest else None
    else:
        out["inferred_fx_format"] = None
        out["inferred_vendor_or_plugin"] = head
    return out


def _content_kind(sample: bytes) -> str:
    if not sample:
        return "empty"
    textish = sum(1 for b in sample[:8000] if 32 <= b <= 126 or b in (9, 10, 13))
    if textish / max(len(sample[:8000]), 1) > 0.85:
        return "text"
    return "binary"


def analyze_preset_file(
    path: Path,
    *,
    rel: str | None = None,
) -> dict:
    """
    Stat + shallow content sniff: INI sections, line count (text), binary flag.
    """
    try:
        st = path.stat()
    except OSError as e:
        return {"path": rel or str(path), "error": str(e)}

    size = st.st_size
    row: dict = {
        "path": rel or path.name,
        "size": size,
        "mtime": int(st.st_mtime),
        "extension": path.suffix.lower(),
    }
    row.update(_infer_from_relative(rel or path.name))

    if size == 0:
        row["content_kind"] = "empty"
        return row

    read_len = min(size, _MAX_READ)
    try:
        raw = path.read_bytes()[:read_len]
    except OSError as e:
        row["read_error"] = str(e)
        return row

    kind = _content_kind(raw)
    row["content_kind"] = kind
    if kind == "binary" and size > _MAX_READ:
        row["note"] = f"binary/large; only first {read_len} bytes sampled"

    if kind == "text":
        text = raw.decode("utf-8", errors="replace")
        row["line_count"] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        rel_l = (rel or "").lower()
        if path.suffix.lower() == ".ini" or "presets/" in rel_l or "/presets/" in rel_l:
            sections = _SECTION.findall(text)
            if sections:
                row["ini_section_names"] = sections[:40]
                row["ini_section_count"] = len(sections)
        # First non-empty line as title hint (some presets store a display name)
        for line in text.splitlines()[:30]:
            s = line.strip()
            if s and not s.startswith(("#", ";", "[")):
                if len(s) < 200:
                    row["first_substantive_line_preview"] = s
                break

    if size > _MAX_READ:
        extra = f"read capped at {read_len} of {size} bytes"
        prev = row.get("note")
        row["note"] = f"{prev}; {extra}" if prev else extra

    return row


def walk_preset_trees(
    *,
    resource_path: Path,
    include_reaper_resource_presets: bool = True,
    include_effects_rpl: bool = True,
    include_audio_presets_user: bool = True,
    max_files_per_tree: int | None = 10_000,
) -> dict:
    """
    Walk presets/, Effects/*.rpl, and optionally ~/Library/Audio/Presets.
    Returns structured summary + per-file details (capped per tree).
    Sections can be skipped independently (e.g. Audio/Presets-only via audio-inspect).
    """
    out: dict = {}

    if include_reaper_resource_presets:
        pr = resource_path / "presets"
        if pr.is_dir():
            files: list[dict] = []
            by_top: dict[str, int] = {}
            by_ext: dict[str, int] = {}
            n = 0
            for dirpath, _dn, filenames in os.walk(pr):
                for fn in filenames:
                    if max_files_per_tree is not None and n >= max_files_per_tree:
                        break
                    fp = Path(dirpath) / fn
                    try:
                        rel = fp.relative_to(resource_path).as_posix()
                    except ValueError:
                        rel = str(fp)
                    files.append(analyze_preset_file(fp, rel=rel))
                    top = rel.split("/")[1] if "/" in rel else rel
                    by_top[top] = by_top.get(top, 0) + 1
                    ext = Path(fn).suffix.lower() or "(no extension)"
                    by_ext[ext] = by_ext.get(ext, 0) + 1
                    n += 1
                if max_files_per_tree is not None and n >= max_files_per_tree:
                    break
            out["reaper_resource_presets"] = {
                "root": str(pr.resolve()),
                "present": True,
                "file_count": n,
                "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
                "by_first_path_component_under_presets": dict(sorted(by_top.items())),
                "files": files,
                "truncated": max_files_per_tree is not None and n >= max_files_per_tree,
            }
        else:
            out["reaper_resource_presets"] = {
                "root": str(pr.resolve()),
                "present": False,
                "file_count": 0,
                "files": [],
                "truncated": False,
            }
    else:
        out["reaper_resource_presets"] = {
            "skipped": True,
            "reason": "REAPER resource presets/ not requested",
            "files": [],
        }

    if include_audio_presets_user:
        ap = paths.user_audio_presets()
        if ap.is_dir():
            files2: list[dict] = []
            by_ext: dict[str, int] = {}
            by_vendor: dict[str, int] = {}
            n2 = 0
            for dirpath, _dn, filenames in os.walk(ap):
                for fn in filenames:
                    if max_files_per_tree is not None and n2 >= max_files_per_tree:
                        break
                    fp = Path(dirpath) / fn
                    try:
                        rel = fp.relative_to(ap).as_posix()
                    except ValueError:
                        rel = fn
                    vendor = rel.split("/")[0] if "/" in rel else "(top)"
                    ext = Path(fn).suffix.lower() or "(no extension)"
                    by_ext[ext] = by_ext.get(ext, 0) + 1
                    by_vendor[vendor] = by_vendor.get(vendor, 0) + 1
                    files2.append(
                        analyze_preset_file(fp, rel=f"Audio/Presets/{rel}")
                    )
                    n2 += 1
                if max_files_per_tree is not None and n2 >= max_files_per_tree:
                    break
            top_v = sorted(by_vendor.items(), key=lambda x: -x[1])[:50]
            out["audio_presets_user"] = {
                "root": str(ap.resolve()),
                "present": True,
                "file_count": n2,
                "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
                "by_vendor_folder": dict(top_v),
                "files": files2,
                "truncated": max_files_per_tree is not None and n2 >= max_files_per_tree,
            }
        else:
            out["audio_presets_user"] = {
                "root": str(ap.resolve()),
                "present": False,
                "file_count": 0,
                "files": [],
                "truncated": False,
            }
    else:
        out["audio_presets_user"] = {
            "skipped": True,
            "reason": "scan of ~/Library/Audio/Presets was disabled",
            "files": [],
        }

    # Literal .rpl files (REAPER preset library) live under Effects/ for JSFX / stock effects.
    # Third-party VST/AU "user presets" are usually .ini under presets/, even if the FX UI says "(.rpl)".
    if include_effects_rpl:
        ef = resource_path / "Effects"
        if ef.is_dir():
            files_rpl: list[dict] = []
            by_author: dict[str, int] = {}
            n3 = 0
            for dirpath, _dn, filenames in os.walk(ef):
                for fn in filenames:
                    if not fn.lower().endswith(".rpl"):
                        continue
                    if max_files_per_tree is not None and n3 >= max_files_per_tree:
                        break
                    fp = Path(dirpath) / fn
                    try:
                        rel = fp.relative_to(resource_path).as_posix()
                    except ValueError:
                        rel = str(fp)
                    files_rpl.append(analyze_preset_file(fp, rel=rel))
                    try:
                        rel_to_effects = fp.relative_to(ef).as_posix()
                        author = rel_to_effects.split("/")[0] if "/" in rel_to_effects else "(top)"
                    except ValueError:
                        author = "(top)"
                    by_author[author] = by_author.get(author, 0) + 1
                    n3 += 1
                if max_files_per_tree is not None and n3 >= max_files_per_tree:
                    break
            out["reaper_effects_rpl"] = {
                "root": str(ef.resolve()),
                "present": True,
                "file_count": n3,
                "by_extension": {".rpl": n3} if n3 else {},
                "by_author_folder": dict(sorted(by_author.items(), key=lambda x: -x[1])),
                "files": files_rpl,
                "truncated": max_files_per_tree is not None and n3 >= max_files_per_tree,
                "note": "On-disk .rpl files for JSFX / REAPER Effects. VST/AU user presets are usually .ini in presets/.",
            }
        else:
            out["reaper_effects_rpl"] = {
                "root": str(ef.resolve()),
                "present": False,
                "file_count": 0,
                "by_extension": {},
                "files": [],
                "truncated": False,
                "note": "Effects/ missing; literal .rpl preset files normally live here.",
            }
    else:
        out["reaper_effects_rpl"] = {
            "skipped": True,
            "reason": "REAPER Effects/*.rpl not requested",
            "files": [],
        }

    return out


def walk_audio_presets_at(
    root: Path,
    *,
    max_files_per_tree: int | None = 10_000,
) -> dict:
    """
    Deep inventory of one Library/Audio/Presets tree (user or system).
    Same per-file analysis as audio_presets_user in walk_preset_trees.
    """
    if not root.is_dir():
        return {
            "root": str(root.resolve()),
            "present": False,
            "file_count": 0,
            "files": [],
            "truncated": False,
        }
    files2: list[dict] = []
    by_ext: dict[str, int] = {}
    by_vendor: dict[str, int] = {}
    n2 = 0
    for dirpath, _dn, filenames in os.walk(root):
        for fn in filenames:
            if max_files_per_tree is not None and n2 >= max_files_per_tree:
                break
            fp = Path(dirpath) / fn
            try:
                rel = fp.relative_to(root).as_posix()
            except ValueError:
                rel = fn
            vendor = rel.split("/")[0] if "/" in rel else "(top)"
            ext = Path(fn).suffix.lower() or "(no extension)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            by_vendor[vendor] = by_vendor.get(vendor, 0) + 1
            files2.append(analyze_preset_file(fp, rel=f"Audio/Presets/{rel}"))
            n2 += 1
        if max_files_per_tree is not None and n2 >= max_files_per_tree:
            break
    top_v = sorted(by_vendor.items(), key=lambda x: -x[1])[:50]
    return {
        "root": str(root.resolve()),
        "present": True,
        "file_count": n2,
        "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
        "by_vendor_folder": dict(top_v),
        "files": files2,
        "truncated": max_files_per_tree is not None and n2 >= max_files_per_tree,
    }


def run_preset_details(
    *,
    resource_path: Path | None = None,
    include_audio_presets_user: bool = True,
    max_files_per_tree: int | None = 10_000,
) -> dict:
    resource_path = paths.resolve_resource_path(resource_path)
    payload = walk_preset_trees(
        resource_path=resource_path,
        include_audio_presets_user=include_audio_presets_user,
        max_files_per_tree=max_files_per_tree,
    )
    payload["resource_path"] = str(resource_path)
    ini = resource_path / "reaper.ini"
    rr = payload.get("reaper_resource_presets") or {}
    ap = payload.get("audio_presets_user") or {}
    er = payload.get("reaper_effects_rpl") or {}
    n_rr = 0 if rr.get("skipped") else int(rr.get("file_count") or 0)
    n_ap = 0 if ap.get("skipped") else int(ap.get("file_count") or 0)
    n_er = 0 if er.get("skipped") else int(er.get("file_count") or 0)
    payload["resource_path_status"] = {
        "resource_dir_exists": resource_path.is_dir(),
        "reaper_ini_present": ini.is_file(),
        "presets_subdir": str((resource_path / "presets").resolve()),
        "effects_subdir": str((resource_path / "Effects").resolve()),
    }
    payload["methodology"] = (
        "On disk, literal .rpl files are under <resource>/Effects/ (JSFX / REAPER effect presets). "
        "Third-party VST/AU user presets are usually stored as .ini under presets/ — the FX window may still "
        "label the menu “User Presets (.rpl)” even when the file on disk is .ini. "
        "by_extension under reaper_resource_presets compares .ini vs other types there. "
        "INI-style [sections] are listed when the file looks like text; binary blobs get size/mtime only."
    )
    if n_rr + n_ap + n_er == 0:
        payload["empty_scan_hints"] = [
            "No preset files were found under presets/, Effects/*.rpl, or (unless skipped) ~/Library/Audio/Presets. "
            "Plug-in presets from REAPER’s save dialog usually live under <resource>/presets/ (often .ini for VST/AU) "
            "and/or ~/Library/Audio/Presets/<vendor>/. Literal .rpl files for JSFX live under <resource>/Effects/.",
            "If you use a portable install or a non-default resource folder, set the path REAPER shows "
            "under Options → Show REAPER resource path in explorer/finder: "
            "reaper-backup preset-details --resource PATH --format json "
            "or export REAPER_RESOURCE_PATH=PATH.",
        ]
        if not payload["resource_path_status"]["resource_dir_exists"]:
            payload["empty_scan_hints"].insert(
                0,
                f"Resource path does not exist or is not a directory: {resource_path}",
            )
        elif not payload["resource_path_status"]["reaper_ini_present"]:
            payload["empty_scan_hints"].insert(
                0,
                "reaper.ini was not found at the resource path — this may not be your live REAPER "
                "profile; use --resource or REAPER_RESOURCE_PATH.",
            )
    return payload
