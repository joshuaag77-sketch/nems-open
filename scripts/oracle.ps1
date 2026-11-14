<#
.SYNOPSIS
  Build and run an oracle inside WSL: scripts\oracle.ps1 <module> [gen] [build] [run] [-LocalOut]

.DESCRIPTION
  A thin wrapper for sessions on Windows: it finds the real EIA checkout (nems-upstream is a junction that
  WSL may not follow), hands it and the shared oracle cache to WSL, and calls oracle/build_wsl.sh.
  With no step named it does gen, build and run. See docs/wsl-oracle.md.

.EXAMPLE
  scripts\oracle.ps1 comm
  scripts\oracle.ps1 resd build run -LocalOut
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Module,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Steps,
    [switch]$LocalOut
)
$ErrorActionPreference = 'Stop'

$distros = (wsl.exe -l -q 2>$null) -join ''
if ($LASTEXITCODE -ne 0 -or -not $distros.Trim()) {
    throw 'WSL has no Linux distribution. Install one: wsl --install -d Ubuntu (then restart), and set it up per docs/wsl-oracle.md.'
}

$repo = Split-Path -Parent $PSScriptRoot
$up = Join-Path $repo 'nems-upstream'
$item = Get-Item $up
if ($item.Target) { $up = @($item.Target)[0] }       # follow the junction
$env:NEMS_UPSTREAM = $up
if (-not $env:NEMS_ORACLE_DIR) { $env:NEMS_ORACLE_DIR = Join-Path $env:USERPROFILE 'dev\oracle-cache' }
# /p: WSL converts these to /mnt/c/... paths for us
$env:WSLENV = 'NEMS_UPSTREAM/p:NEMS_ORACLE_DIR/p:SCENARIO:NEMS_ORACLE_YEARS:NEMS_ORACLE_WORK'

$script = (wsl.exe wslpath -u ((Join-Path $repo 'oracle\build_wsl.sh') -replace '\', '/')).Trim()
$args = @('bash', $script, $Module) + @($Steps | Where-Object { $_ })
if ($LocalOut) { $args += '--local-out' }
& wsl.exe @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
