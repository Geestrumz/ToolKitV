# ytd_downsize — standalone FiveM resource

A server-side-only FiveM resource that automatically detects and downsizes oversized `.ytd` texture dictionary files. All required files are bundled inside this folder — no other parts of the ToolKitV repository are needed.

## Bundled files

| File | Purpose |
|---|---|
| `ytd_downsize.py` | Python script that reads and rewrites `.ytd` files |
| `Dependencies/texconv.exe` | Microsoft texconv — converts and resizes DDS textures (Windows only) |
| `Dependencies/CodeWalker.Core.dll` | CodeWalker library used to parse `.ytd` files |

## Prerequisites (server machine)

| Requirement | Notes |
|---|---|
| **Windows server** | `texconv.exe` is Windows-only |
| **Python 3** | Must be in PATH as `python3` (Linux) or `python` (Windows). Override with `Config.PythonPath`. |
| **pythonnet** | `pip install pythonnet` — lets Python call the CodeWalker .NET DLL |
| **.NET 6.0 or newer** | Required by CodeWalker.Core.dll — https://dotnet.microsoft.com/download |

No other FiveM resources or frameworks are required.

## Installation

1. Copy the entire `ytd_downsize_fivem/` folder into your server's `resources/` directory.
2. Open `config.lua` and set `Config.ScanDirectory` to the absolute path of the folder that contains your `.ytd` files (e.g. your `resources/` directory itself).
3. Add `ensure ytd_downsize` to your `server.cfg`.
4. Start or restart the server.

## Configuration (`config.lua`)

| Key | Default | Description |
|---|---|---|
| `Config.ScanDirectory` | **nil — must be set** | Absolute path to scan for `.ytd` files (recursively) |
| `Config.ScanInterval` | `300` | Seconds between re-scans while the server is running. `0` = startup only |
| `Config.OversizedThresholdBytes` | `16 MB` | Raw file-size pre-filter; files smaller than this are skipped without loading Python |
| `Config.PythonPath` | `'python3'` | Python interpreter name or absolute path |
| `Config.ScriptPath` | `nil` | Leave nil to use the bundled `ytd_downsize.py`. Set only to override |
| `Config.BackupDirectory` | `nil` | Absolute path to copy original `.ytd` files to before modifying |
| `Config.MinTextureSize` | `8192` | Only process textures whose `width + height >= N` |
| `Config.FormatOptimize` | `false` | Force all textures to BC1/BC3 regardless of source format |
| `Config.Verbose` | `false` | Print extra output from the Python script to the server console |

## How it works

1. On resource start (after a 5-second delay) the Lua script scans `Config.ScanDirectory` recursively for `.ytd` files.
2. Any file whose raw size exceeds `Config.OversizedThresholdBytes` is flagged.
3. If flagged files exist, `ytd_downsize.py` is called with `--only-oversized`, which performs a second check based on the RSC7 physical size header, then downsizes textures using `texconv.exe`.
4. The scan repeats every `Config.ScanInterval` seconds.
