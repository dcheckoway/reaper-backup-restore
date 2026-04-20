"""Inspect Cockos Export configuration zip and compare to resource file list."""

from __future__ import annotations

import zipfile
from pathlib import Path


def list_zip_members(zip_path: Path) -> list[tuple[str, int]]:
    """Return (name, file_size_uncompressed) sorted by name."""
    out: list[tuple[str, int]] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out.append((info.filename, info.file_size))
    return sorted(out, key=lambda x: x[0])


def compare_zip_to_paths(
    zip_path: Path,
    resource_files_relative: set[str],
) -> dict[str, list[str]]:
    """
    resource_files_relative: posix-style paths relative to REAPER resource root.
    Zip names may use different separators; normalize to posix.
    """
    zip_names = {p.replace("\\", "/") for p, _ in list_zip_members(zip_path)}
    disk = resource_files_relative
    only_zip = sorted(zip_names - disk)
    only_disk = sorted(disk - zip_names)
    both = sorted(zip_names & disk)
    return {
        "only_in_zip": only_zip,
        "only_on_disk": only_disk,
        "in_both": both,
    }
