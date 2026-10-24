<#
.SYNOPSIS
  Registers (or removes) a per-user Scheduled Task that starts the dashboard server at logon, windowless.
.EXAMPLE
  .\install-startup-task.ps1            # install + start now
  .\install-startup-task.ps1 -Uninstall
#>
param([switch]$Uninstall)

$taskName = "EinkDashboardServer"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "server\server.py"

if ($Uninstall) {
    schtasks /Delete /TN $taskName /F | Out-Null
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*server\server.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "Removed task $taskName and stopped the server."
    exit 0
}

$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $py = (Get-Command python.exe).Source
    $pythonw = Join-Path (Split-Path $py) "pythonw.exe"
}
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found; install Python 3.11+ for the current user" }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2
Write-Host "Task '$taskName' registered for logon and started. State: $((Get-ScheduledTask -TaskName $taskName).State)"
Write-Host "Logs: $root\logs\server.log"
