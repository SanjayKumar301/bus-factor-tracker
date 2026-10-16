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

# Everything is appended through cmd.exe: it writes Python's UTF-8 output byte
# for byte (Windows PowerShell's own >> would re-encode it as UTF-16), and,
# unlike Add-Content, it still works while another program (an editor, a
# `tail -f`) has the log open.
cmd /c "echo.>> `"$LogFile`" & echo ===== Sync started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====>> `"$LogFile`""
cmd /c "`"$Python`" -u `"$SyncScript`" >> `"$LogFile`" 2>&1"
$ExitCode = $LASTEXITCODE
cmd /c "echo ===== Sync finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (exit $ExitCode) =====>> `"$LogFile`""
exit $ExitCode
