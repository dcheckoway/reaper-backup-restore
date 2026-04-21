# reaper-backup

Evidence-based **discovery**, **lean backup**, **restore**, and **Cockos export zip inspection** for [REAPER](https://www.reaper.fm/) on macOS. This is a **stdlib-only** Python 3.10+ CLI—no web stack.

Progress messages go to **stderr** on every subcommand (phases and periodic counts for long walks). Use **`--quiet`** to suppress them when piping **`--format json`** to a file.

## Install

**From a clone (recommended): use a virtual environment** so the editable install stays isolated:

```bash
cd reaper-backup-restore
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
reaper-backup --help
```

Run `deactivate` when you are done with that shell session. Recreate the venv if you change Python versions.

**Without a venv** (global or existing environment):

```bash
pip install -e .
reaper-backup --help
```

## Commands

| Command | Purpose |
|--------|---------|
| `dump` | Read-only audit: REAPER resource tree, `reaper.ini` path hints, plug-in bundles under standard Audio Plug-Ins trees, `~/Library/Audio/Presets`, project roots, sidecar counts (`*.reapeaks`, `*.rpp-bak`), optional `.rpp` summaries. Optional **`--preset-details`** adds a deep preset inventory (see `preset-details`). |
| `preset-details` | **Preset-focused** report: **`presets/`** (VST/AU `.ini` etc.), **`Effects/*.rpl`**, optionally **`~/Library/Audio/Presets`**. Per file: size, mtime, text vs binary, INI **`[section]`** names when applicable, path hints — not filenames only. |
| `audio-inspect` | **`~/Library/Audio/Plug-Ins`** (AU/VST/VST3/CLAP bundles + paths + mtime) and **`~/Library/Audio/Presets`** (same per-file detail as `preset-details` for that tree). Optional **`/Library/...`** with flags. No REAPER resource walk — use `preset-details` for `Application Support/REAPER`. |
| `plugin-inventory` | **Installed plug-ins only** (no presets): **`~/Library/Audio/Plug-Ins`** bundle scan, optional **`/Library/Audio/Plug-Ins`**, optional **`UserPlugins`** under the REAPER resource path. JSON includes **`summary`** and per-bundle paths. Extra VST folders configured only inside REAPER are **not** scanned. |
| `project-inspect` | Parse **`.rpp`**: **master** FX chain + **each track** — plugin format (AU/VST/…), display name, **`PRESETNAME`** when present, **bypass** flag. One or more project paths; JSON under **`files`**. |
| `backup` | Copy into an output directory + **`manifest.json`**. Default is **lean** (skips regenerable caches / scan INIs unless flags). Use **`--comprehensive`** for a full **`Application Support/REAPER`** mirror + host cache so coverage aligns with **`export-audit`** / **`preset-details`**. |
| `restore` | Apply a backup in **canonical order** (see `RESTORE.md`). Supports **`--dry-run`**, **`--map-user OLD=NEW`**, and **`--home`** for the destination profile. |
| `config-inspect` | Inspect a Cockos **Export configuration** zip: summary + **member table** (first **40** paths by default; **`--list`** for all); optional **`--compare-with`** a `dump` JSON to diff zip vs live resource files. |
| `export-audit` | Inspect the **live** resource folder (no zip): heuristics per Cockos export categories, optional `.rpp` scan for JSFX (`<JS` lines). Use before exporting to see what to tick. **JSON** includes full `categories` metrics; **`--format text`** prints an **Evidence** section (paths, file counts, sizes) behind each recommendation. |

### Examples

```bash
# Full discovery JSON (default)
reaper-backup dump > dump.json

# Include rich preset inventory under key preset_details (JSON)
reaper-backup dump --preset-details > dump-with-presets.json

# Same preset logic as a standalone command
reaper-backup preset-details --format json > presets.json

# Library/Audio only: plug-in bundles + Audio/Presets file details (no dump, no REAPER resource tree)
reaper-backup audio-inspect --format json > audio.json
reaper-backup audio-inspect --include-system-plug-ins --include-system-presets --format text

# Installed plug-ins only (reinstall checklist): user + optional system Audio/Plug-Ins + REAPER UserPlugins
reaper-backup plugin-inventory --format json --quiet > plugins-installed.json
reaper-backup plugin-inventory --include-system-plugins --format json --quiet > plugins-with-system.json

# Per-track + master FX and presets from saved projects
reaper-backup project-inspect ~/Documents/REAPER\ Media/MySong.RPP --format json
reaper-backup project-inspect a.RPP b.RPP --format text

# Human-readable summary
reaper-backup dump --format text

# Backup to a folder (lean default)
reaper-backup backup --output ~/Desktop/reaper-backup-run

# Full disk scope aligned with export-audit + preset-details (resource + host cache + scan INIs + …)
reaper-backup backup --output ~/Desktop/reaper-backup-run --comprehensive

# Dry-run (no writes; counts manifest entries)
reaper-backup backup --output ~/Desktop/reaper-backup-run --dry-run

# Same with profile label in JSON
reaper-backup backup --output ~/Desktop/reaper-backup-run --comprehensive --dry-run

# Include official export zip from REAPER → Preferences → General → Export configuration
reaper-backup backup --output ~/Desktop/bak --official-export ~/Desktop/reaper-config.zip

# Decide what to tick in REAPER → Export configuration (reads disk + optional projects)
reaper-backup export-audit --format text

# JSFX check across every .rpp found under reaper.ini paths and --project-root / --extra-root
reaper-backup export-audit --all-rpp --format text

# Any subcommand: JSON on stdout only with --quiet (progress is on stderr)
reaper-backup dump --format json --quiet > dump.json
reaper-backup export-audit --format json --quiet > audit.json

# Inspect one export-audit category from JSON (e.g. Color themes)
reaper-backup export-audit --format json --quiet | jq '.categories.color_themes'

# Cockos export zip: summary + first 40 member paths (add --list for every file)
reaper-backup config-inspect ~/Desktop/reaper-config.zip

# Compare Cockos zip to a prior dump
reaper-backup config-inspect ~/Desktop/reaper-config.zip --compare-with dump.json

# Restore on a new machine (preview)
reaper-backup restore --from ~/Desktop/reaper-backup-run --dry-run

# Restore with home remap
reaper-backup restore --from ~/Desktop/reaper-backup-run --map-user /Users/olduser=/Users/newuser

# Restore when the target account’s home is not the current user (explicit destination home)
reaper-backup restore --from ~/Desktop/reaper-backup-run --home /Users/otheruser --dry-run
```

## Methodology

- **Primary source of truth**: What exists on **your Mac at backup time** (re-run after OS or REAPER updates).
- **Secondary**: Vendor docs for stable layout rules (e.g. Steinberg VST3 locations, Apple Audio Units paths). Use those to interpret what you see locally—not as a substitute for checking paths on disk.
- **REAPER**: The live **resource path** is authoritative (e.g. `~/Library/Application Support/REAPER`). Confirm in REAPER via **Options → Show REAPER resource path in explorer/finder**.

## Lean backup defaults

By default, the tool **skips** regenerable data (host cache, `MetadataCaches/`, `QueuedRenders/`, plug-in scan INIs, `*.reapeaks`, Finder noise like `.DS_Store` / `._*`) unless you opt in with the corresponding `--include-…` flags. **`--comprehensive`** turns on a **full resource mirror** plus **host cache** and the lean opt-ins so your backup matches what **`dump`**, **`export-audit`**, and **`preset-details`** see on disk (still add **`--official-export`** if you want the Cockos zip as a reference artifact). The manifest includes **`backup_profile`** (`lean` vs `comprehensive`) and **`coverage_notes`**.

See `RESTORE.md` for the **canonical restore order** and first-launch rescan behavior.

## License

Tool code is under the [MIT License](LICENSE). REAPER is a trademark of Cockos Incorporated.
