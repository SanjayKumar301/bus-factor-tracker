# Runs one full sync and appends its output to logs\sync.log.
# This is what the scheduled task calls; you can also run it by hand:
#   powershell -ExecutionPolicy Bypass -File scripts\run_sync.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "sync.log"

$Python = (Get-Command python -ErrorAction Stop).Source
$SyncScript = Join-Path $PSScriptRoot "sync_mysql.py"
$env:PYTHONIOENCODING = "utf-8"

Add-Content -Path $LogFile -Encoding utf8 -Value "`n===== Sync started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
# Redirect through cmd.exe so Python's UTF-8 output goes to the log byte for
# byte — Windows PowerShell's own >> would re-encode it as UTF-16.
cmd /c "`"$Python`" -u `"$SyncScript`" >> `"$LogFile`" 2>&1"
$ExitCode = $LASTEXITCODE
Add-Content -Path $LogFile -Encoding utf8 -Value "===== Sync finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (exit $ExitCode) ====="
exit $ExitCode
