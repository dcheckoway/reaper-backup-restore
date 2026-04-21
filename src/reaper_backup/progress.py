"""Progress lines to stderr (keep stdout clean for JSON / piping)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path


def stderr_line(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def make_log(verbose: bool) -> Callable[[str], None]:
    return stderr_line if verbose else lambda _m: None


def find_rpp_files_with_progress(
    roots: list[Path],
    *,
    log: Callable[[str], None],
    prefix: str = "reaper-backup",
    discover_interval: int = 200,
) -> list[Path]:
    """Walk trees for *.rpp; log periodically (discovery can take a long time)."""
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            log(f"{prefix}: skip missing directory: {root}")
            continue
        log(f"{prefix}: searching for .rpp under {root.resolve()} …")
        for dirpath, _dn, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(".rpp"):
                    found.append(Path(dirpath) / fn)
                    n = len(found)
                    if n % discover_interval == 0:
                        log(f"{prefix}: … {n} .rpp files found so far")
    log(f"{prefix}: sorting {len(found)} project paths …")
    return sorted(found)
