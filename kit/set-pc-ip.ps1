# set-pc-ip.ps1 -- write the PC's LAN IP into port\civ_bridge.js (run once).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\set-pc-ip.ps1 -PcIp 192.168.1.100
param(
  [Parameter(Mandatory = $true)][string]$PcIp
)
$ErrorActionPreference = 'Stop'
$bridge = Join-Path $PSScriptRoot 'port\civ_bridge.js'
if (-not (Test-Path $bridge)) { throw "not found: $bridge" }
$text = Get-Content $bridge -Raw -Encoding UTF8
if ($text -notmatch "'<PC_IP>'") {
  Write-Output 'PC_IP already set; overwriting any previous value.'
  $text = [regex]::Replace($text, "PC_IP:\s*'[^']*'", "PC_IP: '$PcIp'")
} else {
  $text = $text.Replace("'<PC_IP>'", "'$PcIp'")
}
[System.IO.File]::WriteAllText($bridge, $text, (New-Object System.Text.UTF8Encoding($false)))
Write-Output "port\civ_bridge.js -> PC_IP = $PcIp"
