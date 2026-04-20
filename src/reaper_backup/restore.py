"""Restore from a backup directory + manifest.json (canonical order)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import paths


@dataclass
class RestoreConfig:
    backup_root: Path
    dry_run: bool = False
    map_user: tuple[str, str] | None = None  # (old_home, new_home) as path strings
    home_dir: Path | None = None


def run_restore(cfg: RestoreConfig) -> list[dict]:
    """
    Apply manifest entries in order. Returns log lines (dicts) for each operation.
    Skips layer 'cockos_export' (reference artifact — keep with backup).
    DRM / vendor installers are manual — see RESTORE.md.
    """
    man_path = cfg.backup_root / "manifest.json"
    if not man_path.is_file():
        raise FileNotFoundError(f"Missing manifest: {man_path}")

    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    data_root = cfg.backup_root / "data"
    entries: list[dict] = list(manifest.get("entries", []))

    source_home = str(manifest.get("source_home", ""))
    new_home = str((cfg.home_dir or paths.home()).expanduser().resolve())

    old_h = source_home
    new_h = new_home
    if cfg.map_user:
        old_h, new_h = cfg.map_user[0], cfg.map_user[1]

    log: list[dict] = []

    def resolve_dest(entry: dict) -> Path | None:
        dt = entry.get("dest_type")
        dsp = entry.get("dest_subpath", "").lstrip("/")
        if dt == "home":
            return Path(new_h).expanduser() / dsp
        if dt == "root":
            return Path("/") / dsp
        if dt == "absolute":
            root = entry.get("source_root", "")
            if old_h and new_h and root.startswith(old_h):
                root = new_h + root[len(old_h) :]
            return Path(root) / entry.get("dest_subpath", "").lstrip("/")
        if dt == "artifact":
            return None
        return None

    entries.sort(key=lambda e: (e.get("order", 0), e.get("src", "")))

    for entry in entries:
        layer = entry.get("layer", "")
        if layer == "cockos_export":
            log.append(
                {
                    "action": "skip",
                    "layer": layer,
                    "reason": "reference zip — compare with config-inspect; not auto-installed",
                    "src": entry.get("src"),
                }
            )
            continue

        src_rel = entry.get("src")
        if not src_rel:
            continue
        src_abs = (data_root / src_rel).resolve()
        if not src_abs.exists():
            log.append(
                {
                    "action": "error",
                    "layer": layer,
                    "src": str(src_rel),
                    "error": "missing path in backup",
                }
            )
            continue

        # REAPER.app is a bundle (directory) stored as one manifest row
        if layer == "reaper_app" and src_abs.is_dir():
            dsp = entry.get("dest_subpath", "Applications/REAPER.app").lstrip("/")
            dest = Path("/") / dsp
            if cfg.dry_run:
                log.append(
                    {
                        "action": "would_copytree",
                        "layer": layer,
                        "src": str(src_abs),
                        "dest": str(dest),
                    }
                )
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src_abs, dest, symlinks=True)
                log.append(
                    {
                        "action": "copytree",
                        "layer": layer,
                        "src": str(src_abs),
                        "dest": str(dest),
                    }
                )
            continue

        if not src_abs.is_file():
            log.append(
                {
                    "action": "error",
                    "layer": layer,
                    "src": str(src_rel),
                    "error": "not a file",
                }
            )
            continue

        dest = resolve_dest(entry)
        if dest is None:
            log.append({"action": "skip", "layer": layer, "src": src_rel})
            continue

        log.append(
            {
                "action": "copy" if not cfg.dry_run else "would_copy",
                "layer": layer,
                "src": str(src_abs),
                "dest": str(dest),
            }
        )
        if not cfg.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_abs, dest)

    return log
