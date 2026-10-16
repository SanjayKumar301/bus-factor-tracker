# Registers a Windows Task Scheduler job that runs the sync once a day, so
# bus_factor_snapshot builds up the history the trend chart and
# sp_declining_repos() need. Run once (no admin rights needed):
#   powershell -ExecutionPolicy Bypass -File scripts\register_sync_task.ps1
#
# Remove it again with:
#   Unregister-ScheduledTask -TaskName "BusFactorTrackerSync" -Confirm:$false

param(
    [string]$At = "09:00"
)

$TaskName = "BusFactorTrackerSync"
$RunScript = Join-Path $PSScriptRoot "run_sync.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)

$Trigger = New-ScheduledTaskTrigger -Daily -At $At

# StartWhenAvailable: if the laptop was off at the scheduled time, run as
# soon as it's back on instead of skipping that day.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Daily GitHub sync for the Bus Factor Tracker DBMS project" -Force | Out-Null

Write-Host "Registered '$TaskName' to run daily at $At. Logs go to logs\sync.log."
