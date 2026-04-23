-- ytd_downsize_fivem/server.lua
-- Server-side monitor: scans for oversized .ytd files and invokes
-- ytd_downsize.py only when at least one oversized file is found.
--
-- Add this resource to your server.cfg:
--   ensure ytd_downsize
--
-- Then edit config.lua and set Config.ScanDirectory.

local resourceName = GetCurrentResourceName()

-- ─── Logging ─────────────────────────────────────────────────────────────────

local function log(msg)
    print(('[ytd_downsize] %s'):format(msg))
end

-- ─── File helpers ─────────────────────────────────────────────────────────────

--- Return the byte size of a file, or 0 on error.
local function getFileSize(path)
    local f = io.open(path, 'rb')
    if not f then return 0 end
    local size = f:seek('end')
    f:close()
    return size or 0
end

--- Return true if a regular file exists and is readable.
local function fileExists(path)
    local f = io.open(path, 'rb')
    if f then f:close() return true end
    return false
end

-- ─── Directory scanning ───────────────────────────────────────────────────────

--- Recursively find all .ytd files under `directory`.
--- Returns a list of absolute paths.
local function findYTDFiles(directory)
    local files = {}
    local isWindows = package.config:sub(1, 1) == '\\'

    local cmd
    if isWindows then
        -- dir /s /b lists files recursively with full paths
        cmd = ('dir /s /b "%s\\*.ytd" 2>nul'):format(directory)
    else
        cmd = ('find "%s" -name "*.ytd" -type f 2>/dev/null'):format(directory)
    end

    local handle = io.popen(cmd)
    if not handle then
        log('ERROR: Could not open directory listing process for: ' .. directory)
        return files
    end

    for line in handle:lines() do
        -- Trim leading/trailing whitespace (Windows paths can have trailing CR)
        line = line:match('^%s*(.-)%s*$')
        if line ~= '' then
            table.insert(files, line)
        end
    end
    handle:close()

    return files
end

--- Scan `directory` for .ytd files whose raw size exceeds `thresholdBytes`.
--- Returns (hasOversized: bool, totalCount: number, oversizedPaths: table).
local function findOversizedYTDs(directory, thresholdBytes)
    local ytdFiles   = findYTDFiles(directory)
    local oversized  = {}

    for _, path in ipairs(ytdFiles) do
        if getFileSize(path) > thresholdBytes then
            table.insert(oversized, path)
        end
    end

    return #oversized > 0, #ytdFiles, oversized
end

-- ─── Script path resolution ──────────────────────────────────────────────────

--- Return the path to ytd_downsize.py, checking Config.ScriptPath first,
--- then several locations relative to this resource.
local function resolveScriptPath()
    if Config.ScriptPath then
        if fileExists(Config.ScriptPath) then
            return Config.ScriptPath
        end
        log('WARNING: Config.ScriptPath set but file not found: ' .. Config.ScriptPath)
        return nil
    end

    -- Auto-detect relative to the resource directory
    local resourcePath = GetResourcePath(resourceName)
    local candidates = {
        resourcePath .. '/../../ytd_downsize.py',  -- ToolKitV repo root (two levels up)
        resourcePath .. '/../ytd_downsize.py',     -- one level up
        resourcePath .. '/ytd_downsize.py',        -- inside this resource
    }

    for _, candidate in ipairs(candidates) do
        if fileExists(candidate) then
            return candidate
        end
    end

    return nil
end

-- ─── Downsizer invocation ────────────────────────────────────────────────────

--- Build and execute the ytd_downsize.py command.
--- Returns true on success.
local function runDownsizer(scriptPath, scanDir)
    local cmd = ('"%s" "%s" --input "%s" --only-oversized'):format(
        Config.PythonPath,
        scriptPath,
        scanDir
    )

    if Config.BackupDirectory then
        cmd = cmd .. (' --backup "%s"'):format(Config.BackupDirectory)
    end

    if Config.MinTextureSize then
        cmd = cmd .. (' --min-size %d'):format(Config.MinTextureSize)
    end

    if Config.FormatOptimize then
        cmd = cmd .. ' --format-optimize'
    end

    if Config.Verbose then
        cmd = cmd .. ' --verbose'
    end

    log('Executing: ' .. cmd)
    local exitCode = os.execute(cmd)

    -- os.execute returns true/0 on success depending on Lua version
    return exitCode == 0 or exitCode == true
end

-- ─── Main scan logic ─────────────────────────────────────────────────────────

local function doScan()
    local scanDir = Config.ScanDirectory
    if not scanDir then
        log('ERROR: Config.ScanDirectory is not set. Edit config.lua before starting the resource.')
        return
    end

    log(('Scanning "%s" for oversized .ytd files...'):format(scanDir))

    local hasOversized, total, oversizedFiles = findOversizedYTDs(
        scanDir,
        Config.OversizedThresholdBytes
    )

    if not hasOversized then
        log(('No oversized .ytd files found (scanned %d file(s)). Skipping downsizer.'):format(total))
        return
    end

    log(('Found %d oversized .ytd file(s) out of %d total. Starting downsizer...'):format(
        #oversizedFiles, total
    ))

    if Config.Verbose then
        for _, path in ipairs(oversizedFiles) do
            local sizeMB = getFileSize(path) / (1024 * 1024)
            log(('  oversized: %s  (%.2f MB)'):format(path, sizeMB))
        end
    end

    local scriptPath = resolveScriptPath()
    if not scriptPath then
        log('ERROR: ytd_downsize.py not found. Set Config.ScriptPath in config.lua or place '
            .. 'ytd_downsize.py in the ToolKitV root directory.')
        return
    end

    local ok = runDownsizer(scriptPath, scanDir)
    if ok then
        log('Downsizing complete.')
    else
        log('WARNING: ytd_downsize.py exited with an error. Check the console output above.')
    end
end

-- ─── Event hooks ─────────────────────────────────────────────────────────────

AddEventHandler('onResourceStart', function(startedResource)
    if startedResource ~= resourceName then return end

    log('YTD downsize monitor started.')

    -- Small delay so the server has finished loading before we scan
    SetTimeout(5000, function()
        doScan()
    end)
end)

-- ─── Periodic re-scan ────────────────────────────────────────────────────────

if Config.ScanInterval and Config.ScanInterval > 0 then
    CreateThread(function()
        -- Wait for the startup scan plus the first interval before rescanning
        Wait((Config.ScanInterval * 1000) + 6000)
        while true do
            doScan()
            Wait(Config.ScanInterval * 1000)
        end
    end)
end
