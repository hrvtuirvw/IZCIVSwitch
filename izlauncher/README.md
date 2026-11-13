# IZlauncher 0.27 (Civ7) for IZCIVSwitch

Optional menu package for the CivSwitch / ns2jb chain. It installs a
`Load Game` entry and an immutable menu capsule into the game's `save:`
storage. The menu includes the stock Remote JS Loader, started with a
controller gesture.

This package is **not required for FS**. The verified FS run used the Lobby
path; the launcher is an optional UI entry.

## Contents

```
izlauncher/
├── install.py          installer / checker / rollback
├── install.sh          shell wrapper
├── install.ps1         PowerShell wrapper
├── package/
│   ├── IZlauncher-027-FS.Civ7Save   trigger save, 1 212 487 bytes
│   ├── menu-capsule.bin             menu + embedded loader, 336 819 bytes
│   ├── boot.js / capsule-source.js  source for audit
│   ├── pad-normalize.comp.spv
│   └── manifest.json                sizes and SHA-256 (relative paths)
└── receipts/<uuid>/receipt.json     created on install
```

`package/` is the build from `izlauncher-civ7-027-fs-20261111`; only the
manifest paths are relative, the hashes are unchanged.

## What installation does

1. Validates the local files against `manifest.json`.
2. Uploads the menu capsule to `save:/IZ2S/launcher022/menu-<hash>.bin`:
   staging → full SHA-256 **on the console** → copy to the final path →
   `Commit("save")`.
3. Reads and saves the previous trigger to
   `save:/IZ2SOffline/<uuid>/previous.bin`.
4. Uploads the trigger to `save:/saves/Single/IZ2S.Civ7Save` using the same
   staged/verified/publish sequence.
5. Writes `receipts/<uuid>/receipt.json`.

After installation the menu runs offline from `save:`; no PC transport is
needed. This is the same scheme as the hardware-verified 0.22 build, with the
embedded loader added in 0.27.

## Start the loader from the menu

The stock CivSwitch Remote JS Loader is embedded in the 0.27 capsule but does
not start at boot. In the menu, **double-press R3** (right stick). The menu
loop stops, the last frame stays on screen, and the loader listens on `:9026`.

Then on the PC:

```bash
python3 ../IZCIVSwitch.py --no-lobby
```

## Install

1. Arm the Remote JS Loader first:
   - Lobby path: `IZCIVSwitch.py --lobby --inject-only`, or
   - the kit's `XSTRIG.Civ7Save` row.
2. Wait for `Awaiting payload at <IP>:9026`.
3. On the PC:

```bash
python install.py --ip <S2-IP> --check
python install.py --ip <S2-IP>
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -ip <S2-IP>
```

4. Wait for `INSTALL DONE`, close Civ7 completely (HOME/X), start it again,
   open `Load Game`, and select `IZ2S.Civ7Save`.

## Options

| Option | Meaning |
|---|---|
| `--check` | validate the package; with `--ip`, also probe the loader |
| `--dry-run` | print the plan without writing |
| `--replace-kit-trigger` | write to `XSTRIG.Civ7Save` instead of `IZ2S.Civ7Save` |
| `--name NAME` | another file name under `save:/saves/Single/` |
| `--no-capsule` | do not touch the menu; update only the trigger |
| `--pull-backup` | also pull a copy of the previous trigger to the PC (slow, 512-byte reads) |
| `--restore RECEIPT` | roll back using a receipt |
| `--kit DIR` | path to `civswitch-kit` (default: `../kit`) |

## Rollback

The installer keeps the previous trigger on the console and writes a receipt:

```bash
python install.py --ip <S2-IP> --restore receipts/<uuid>/receipt.json
```

The script verifies the backup SHA-256, copies it back to the original path,
and commits the save. If there was no previous trigger (first install), the
receipt says so.

## Compatibility with the kit

- The default trigger is a separate `IZ2S.Civ7Save`, so a kit restore of
  `XSTRIG.Civ7Save` does not overwrite it. Both rows appear in `Load Game`.
- `--replace-kit-trigger` writes `XSTRIG.Civ7Save`; a kit restore without
  `-SkipRestore` will overwrite the launcher.
- `install.py` uses the fs offsets documented in
  `kit/docs/SAVE-BACKUP.md` and warns if they do not match.

## Verification

- Local SHA-256 hashes of the trigger, menu and `boot.js` match the manifest.
- Install and rollback were exercised end-to-end against a mock loader that
  implements the kit's `sdk_base +` fs offsets and the `send_js.py` TCP
  protocol: files on the mock were byte-identical, and rollback restored the
  previous trigger with a matching SHA-256.
- The installer was run on hardware with the 0.22 package (`INSTALL DONE`,
  menu loaded). The 0.27 package was checked through the mock install and rollback path.

## Limitations

- `install.py` requires an already armed loader. Use
  `../IZCIVSwitch.py --lobby --inject-only`, the `XSTRIG` row, or the Switch 1
  NRO to arm it.
- `Commit("save")` runs after each publication. If the process is interrupted
  between staging and publication, a staged file remains on the console. A
  second run in the same game process refuses to continue and asks you to
  restart Civ7. This is intentional: native calls are never replayed.
- `--pull-backup` is slow and optional; working rollback uses the copy on the
  console.
