fx_version 'cerulean'
game 'gta5'

name        'ytd_downsize'
description 'Automatically downsizes oversized YTD texture files using ytd_downsize.py'
version     '1.0.0'
author      'ToolKitV'

-- Server-side only; no client scripts or UI needed
server_scripts {
    'config.lua',
    'server.lua',
}
