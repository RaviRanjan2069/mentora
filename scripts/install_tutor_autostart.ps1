# Run scripts/start_tutor_tunnel.ps1 automatically: at Windows sign-in and then every
# 5 minutes (it only restarts what stopped), hidden, as the current user, no admin needed.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_tutor_autostart.ps1 [-NeverSleepOnAC]
#   powershell -ExecutionPolicy Bypass -File scripts\install_tutor_autostart.ps1 -Remove
#
# -NeverSleepOnAC: while plugged in, the computer never goes to sleep on its own (closing the
# lid still follows Windows' lid setting). Undo: powercfg /change standby-timeout-ac 30

param([switch]$NeverSleepOnAC, [switch]$Remove)

$ErrorActionPreference = "Stop"
$name = "Mentora AI Tutor"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the '$name' task."
    return
}

$script = Join-Path $PSScriptRoot "start_tutor_tunnel.ps1"
# conhost --headless runs PowerShell without flashing a console window.
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument (
    "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`"")
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $atLogon, $every5 `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Installed '$name': runs at sign-in and every 5 minutes (logs: %LOCALAPPDATA%\Mentora\logs)."

if ($NeverSleepOnAC) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "While plugged in, this computer no longer goes to sleep on its own."
}
