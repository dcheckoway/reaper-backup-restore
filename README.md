# reaper-backup

Evidence-based **discovery**, **lean backup**, **restore**, and **Cockos export zip inspection** for [REAPER](https://www.reaper.fm/) on macOS. This is a **stdlib-only** Python 3.10+ CLI—no web stack.

## Install

```bash
pip install -e .
reaper-backup --help
```

## Commands

| Command | Purpose |
|--------|---------|
| `dump` | Read-only audit: REAPER resource tree, `reaper.ini` path hints, plug-in bundles under standard Audio Plug-Ins trees, `~/Library/Audio/Presets`, project roots, sidecar counts (`*.reapeaks`, `*.rpp-bak`), optional `.rpp` summaries. |
| `backup` | Copy lean default set (excludes regenerable caches, scan INIs, peaks unless flags) into an output directory with `manifest.json`. |
| `restore` | Apply a backup in **canonical order** (see `RESTORE.md`). Supports `--dry-run` and `--map-user OLD=NEW`. |
| `config-inspect` | List a Cockos **Export configuration** zip; optional `--compare-with` a `dump` JSON to diff zip vs live resource files. |

### Examples

```bash
# Full discovery JSON (default)
reaper-backup dump > dump.json

# Human-readable summary
reaper-backup dump --format text

# Backup to a folder (lean default)
reaper-backup backup --output ~/Desktop/reaper-backup-run

# Dry-run (no writes; counts manifest entries)
reaper-backup backup --output ~/Desktop/reaper-backup-run --dry-run

# Include official export zip from REAPER → Preferences → General → Export configuration
reaper-backup backup --output ~/Desktop/bak --official-export ~/Desktop/reaper-config.zip

# Compare Cockos zip to a prior dump
reaper-backup config-inspect ~/Desktop/reaper-config.zip --compare-with dump.json

# Restore on a new machine (preview)
reaper-backup restore --from ~/Desktop/reaper-backup-run --dry-run

# Restore with home remap
reaper-backup restore --from ~/Desktop/reaper-backup-run --map-user /Users/olduser=/Users/newuser
```

## Methodology

- **Primary source of truth**: What exists on **your Mac at backup time** (re-run after OS or REAPER updates).
- **Secondary**: Vendor docs for stable layout rules (e.g. Steinberg VST3 locations, Apple Audio Units paths). Use those to interpret what you see locally—not as a substitute for checking paths on disk.
- **REAPER**: The live **resource path** is authoritative (e.g. `~/Library/Application Support/REAPER`). Confirm in REAPER via **Options → Show REAPER resource path in explorer/finder**.

## Lean backup defaults

By default, the tool **skips** regenerable data (host cache, `MetadataCaches/`, `QueuedRenders/`, plug-in scan INIs, `*.reapeaks`, Finder noise like `.DS_Store` / `._*`) unless you opt in with the corresponding `--include-…` flags. See `RESTORE.md` for the **canonical restore order** and first-launch rescan behavior.

## License

Tool code: project license (if added). REAPER is a trademark of Cockos Incorporated.
