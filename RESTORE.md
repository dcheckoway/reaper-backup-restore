# REAPER restore runbook (clean Mac / new user)

Follow this order so REAPER does not launch until files are consistent. It matches the **canonical order** implemented by `reaper-backup restore` (file layers) plus steps that are **manual** (installers, DRM).

## Before you leave the old machine

1. **Export configuration** in REAPER: **Preferences → General → Export configuration** — save the zip to a known path; include it in backup (`--official-export`) or keep it next to your archive.
2. **License / DRM inventory** — note iLok, vendor logins, and seat limits; deactivate seats if the vendor requires it before migration.
3. **Consolidate projects** if you rely on scattered media — use REAPER’s consolidate / save-with-media workflows so paths are predictable.

## Prerequisites on the new system

1. **User / home layout** — Use the same macOS short name and paths as the old machine **or** plan to remap paths (`reaper-backup restore --map-user OLD=NEW`) and fix absolute paths in `reaper.ini` / projects as needed.
2. **Install REAPER** — From Cockos or restore a backed-up `REAPER.app` to `/Applications/`. **Do not launch** yet; if an installer opens REAPER, quit without saving.
3. **Vendor plug-in installers (if needed)** — PKGs that install helpers outside plain bundles should run **before** the first REAPER launch when possible.

## Canonical file restore order

The restore tool applies **layers** in this order (see `manifest.json` entries):

1. **`REAPER.app`** (optional backup) — Copy to `/Applications/` if you backed it up; otherwise rely on step 2 above.
2. **Plug-in bundles** — `~/Library/Audio/Plug-Ins/...` and optionally `/Library/Audio/Plug-Ins/...` (the latter may require `sudo`).
3. **`~/Library/Audio/Presets/`** — Third-party AU-related presets; restore **with** plug-in trees, **before** first REAPER launch.
4. **DRM / authorization** — Run iLok, PACE, or vendor tools **after** bundles exist, **before** first REAPER launch where the vendor allows.
5. **`~/Library/Application Support/REAPER/`** — Full resource folder (license, `reaper.ini`, ReaPack, `UserPlugins`, presets, etc.).
6. **`~/Library/Preferences/com.cockos.reaper.plist`** — Together with or immediately after step 5, **before** first launch.
7. **Projects / media / `--extra-root` trees** — Restore to the **same absolute paths** as before or remap before opening sessions.

**Reference artifact:** A Cockos **Export configuration** zip in the backup is **not** auto-merged into the system — keep it for comparison (`config-inspect`) or manual import; your primary settings come from the resource folder copy.

**Host cache** (`~/Library/Caches/com.cockos.reaper/`) is optional tier-2; lean backups often omit it.

## First launch

1. Launch REAPER.
2. **Rescan plug-ins** (AU / VST / VST3 / CLAP / JS as you use). Lean backups omit scan-cache INIs; a rescan rebuilds them.
3. **Options → Show REAPER resource path** — confirm it points at the restored folder.
4. Open a **known test project**, then a **plugin-heavy** session and a **sample-dependent** session.

## sudo and permissions

Restoring into `/Library/...` may require administrator rights. If `restore` fails with permission errors, copy those layers manually with appropriate ownership.

## Same REAPER version first

Match the **REAPER version** you validated on the old machine before upgrading; that separates migration issues from upgrade issues.
