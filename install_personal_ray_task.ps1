# Install/update the LOCAL Windows Task Scheduler task for Personal RAY.
# Nothing is scheduled by merely pulling the repository.
# Usage: .\install_personal_ray_task.ps1 [-Cadence Daily|SixHourly]
[CmdletBinding()]
param([ValidateSet("Daily", "SixHourly")][string]$Cadence = "Daily")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Windows Task Scheduler is required." }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $root "run_personal_ray.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"
foreach ($item in @($runner, $python, (Join-Path $root ".env"))) {
    if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
        throw "Missing required local file: $item"
    }
}

$executable = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction -Execute $executable -WorkingDirectory $root -Argument (
    '-NoProfile -ExecutionPolicy Bypass -File "' + $runner + '"'
)
if ($Cadence -eq "Daily") {
    $triggers = @(New-ScheduledTaskTrigger -Daily -At "09:00")
} else {
    # Four daily triggers are more reliable than a Windows repetition duration
    # and cap Remotive at its recommended maximum of four requests per day.
    $triggers = @(3, 9, 15, 21) | ForEach-Object {
        New-ScheduledTaskTrigger -Daily -At ("{0:D2}:00" -f $_)
    }
}
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable
$account = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$name = "RAY Personal Job Discovery"
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal -Description (
        "Personal-only jobs discovery. Writes local logs and the dedicated Personal Ray Sheet."
    ) -Force | Out-Null
Write-Host "Scheduled: $name ($Cadence), Windows local time; only while user is logged on."
Write-Host "Review or disable in Task Scheduler. Test the runner manually before relying on it."
