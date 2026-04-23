fx_version 'cerulean'
game 'gta5'

name        'ytd_downsize'
description 'Standalone resource: automatically downsizes oversized YTD files using the bundled ytd_downsize.py, texconv.exe and CodeWalker.Core.dll'
version     '1.0.0'
author      'ToolKitV'

-- Server-side only; no client scripts or UI needed
server_scripts {
    'config.lua',
    'server.lua',
}
