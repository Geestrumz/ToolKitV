-- ytd_downsize_fivem/config.lua
-- Edit this file before starting your server.

Config = {}

-- ─── Required ────────────────────────────────────────────────────────────────

-- Absolute path to the directory (or tree) that contains your .ytd files.
-- Example (Linux):   '/home/user/fivem-server/resources'
-- Example (Windows): 'C:/FiveM/server-data/resources'
Config.ScanDirectory = nil  -- MUST be set

-- ─── Optional ────────────────────────────────────────────────────────────────

-- Seconds between automatic re-scans while the server is running.
-- Set to 0 to scan only once, at resource start.
Config.ScanInterval = 300

-- File-size pre-filter (bytes).  Any .ytd whose raw file size exceeds this
-- value is passed to the Python script.  The Python script performs the
-- proper RSC7 physical-size check and skips truly small files, so this value
-- is just a fast first-pass guard.  Default = 16 MB.
Config.OversizedThresholdBytes = 16 * 1024 * 1024

-- Python interpreter to use.  'python3' works on most Linux servers.
-- Use 'python' on Windows or if python3 is not in PATH.
Config.PythonPath = 'python3'

-- Absolute path to ytd_downsize.py.
-- When nil the resource will search for the script automatically:
--   1. Two directories above this resource folder (ToolKitV repo root)
--   2. One directory above this resource folder
--   3. Inside this resource folder
Config.ScriptPath = nil

-- Optional backup directory.  Original .ytd files are copied here before
-- being modified.  Set to nil to disable backups.
-- Example: '/home/user/fivem-server/ytd_backups'
Config.BackupDirectory = nil

-- Minimum combined texture width+height to optimize.  Textures smaller than
-- this are left untouched.  Mirrors --min-size in ytd_downsize.py.
Config.MinTextureSize = 8192

-- Force all textures to BC1/BC3 format regardless of their original format.
-- Mirrors --format-optimize in ytd_downsize.py.
Config.FormatOptimize = false

-- Print extra output from ytd_downsize.py to the server console.
Config.Verbose = false
