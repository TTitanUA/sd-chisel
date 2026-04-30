# Run backend (uvicorn) and frontend (Vite) in parallel with merged stdout.
# Each line is prefixed with [be]/[fe]. Ctrl+C stops both.
# Implementation lives in dev.mjs (cross-platform).
#
# Usage:  powershell -File scripts\dev.ps1     (or:  .\scripts\dev.ps1)

$ErrorActionPreference = 'Stop'
& node (Join-Path $PSScriptRoot 'dev.mjs') @args
exit $LASTEXITCODE
