"""Lean backup policy: what to skip by default."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


# Plug-in scan cache basenames (exact match) — excluded unless include_plugin_scan_caches
PLUGIN_SCAN_INI_NAMES = frozenset(
    {
        "reaper-recentfx.ini",
    }
)


def _is_plugin_scan_ini(name: str) -> bool:
    n = name.lower()
    if n in {x.lower() for x in PLUGIN_SCAN_INI_NAMES}:
        return True
    if fnmatch.fnmatch(n, "reaper-vstplugins_*.ini"):
        return True
    if fnmatch.fnmatch(n, "reaper-auplugins_*.ini"):
        return True
    if n == "reaper-jsfx.ini":
        return True
    if fnmatch.fnmatch(n, "reaper-clap-*.ini"):
        return True
    return False


@dataclass
class LeanOptions:
    """Options controlling what gets copied."""

    include_plugin_scan_caches: bool = False
    include_metadata_caches: bool = False
    include_queued_renders: bool = False
    include_host_cache: bool = False
    include_peaks: bool = False
    exclude_project_backups: bool = False
    full_resource_mirror: bool = False
    include_os_metadata: bool = False


def is_os_junk_name(name: str) -> bool:
    if name == ".DS_Store":
        return True
    if name == ".localized":
        return True
    if name == "Thumbs.db":
        return True
    if name.startswith("._"):
        return True
    return False


def should_skip_resource_path(
    rel: PurePosixPath,
    *,
    opts: LeanOptions,
) -> bool:
    """Return True if this path (relative to REAPER resource root) should not be backed up."""
    parts = rel.parts
    if not parts:
        return False

    # OS junk anywhere (always skip unless forensic flag)
    if any(is_os_junk_name(p) for p in parts) and not opts.include_os_metadata:
        return True

    # Full mirror: keep caches and scan INIs; only OS junk excluded (handled above)
    if opts.full_resource_mirror:
        return False

    if "MetadataCaches" in parts and not opts.include_metadata_caches:
        return True
    if "QueuedRenders" in parts and not opts.include_queued_renders:
        return True

    name = parts[-1]
    if _is_plugin_scan_ini(name) and not opts.include_plugin_scan_caches:
        return True

    return False


def should_skip_project_file(rel: PurePosixPath, *, opts: LeanOptions) -> bool:
    """Path relative to a project root."""
    parts = rel.parts
    if any(is_os_junk_name(p) for p in parts) and not opts.include_os_metadata:
        return True
    if rel.suffix.lower() == ".reapeaks" and not opts.include_peaks:
        return True
    if "Backups" in parts and rel.suffix.lower() == ".bak" and opts.exclude_project_backups:
        # .rpp-bak
        if str(rel).lower().endswith(".rpp-bak"):
            return True
    return False


def should_skip_generic_file(path: Path, *, opts: LeanOptions) -> bool:
    """Absolute or any path — for plist copy trees etc."""
    if is_os_junk_name(path.name) and not opts.include_os_metadata:
        return True
    return False
