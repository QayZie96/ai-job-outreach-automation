# Windows Task Scheduler entrypoint for RAY Personal Job Discovery.
# Run in the existing personal-only checkout; no global Python or credentials in source control.
# Task Scheduler: one daily trigger, 09:00 local time; ignore new parallel instances.
[CmdletBinding()]
param([switch]$PreviewOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"
$profile = Join-Path $root "profiles\personal_profile.local.txt"
$credential = Join-Path $root "credentials\google-service-account.json"

foreach ($item in @($python, $envFile, $profile)) {
    if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
        throw "Missing local file: $item"
    }
}
if (-not $PreviewOnly -and -not (Test-Path -LiteralPath $credential -PathType Leaf)) {
    throw "Missing Google service account credential. Share the Personal Ray Sheet with its client_email as Editor."
}

Set-Location -LiteralPath $root
if ($PreviewOnly) {
    & $python personal_offline_batch.py --limit 5 --include-review 5
    if ($LASTEXITCODE -ne 0) { throw "Offline preview failed ($LASTEXITCODE)" }
    exit 0
}

$logFolder = Join-Path $root "personal_logs"
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logFolder ("ray-" + $stamp + ".log")
try {
    # Keep report at root: changing its directory would also change the
    # location of the durable, gitignored discovery-history file.
    & $python personal_discovery.py --live --write-sheet 2>&1 |
        Tee-Object -FilePath $logFile
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Personal discovery failed (exit $exitCode). See $logFile" }

    & $python -c "import json,sys; d=json.load(open('personal_run.json',encoding='utf-8')); e=d.get('evaluation',{}); n=e.get('failed_batches',0); print('Summary: '+str(len(d.get('evaluated_jobs',[])))+' jobs, '+str(e.get('gemini_calls',0))+' Gemini calls, '+str(n)+' failed batches'); sys.exit(1 if n else 0)" 2>&1 |
        Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Gemini reported a failed batch; successful jobs remain saved. Next scheduled run can retry. See $logFile"
    }
} finally {
    Get-ChildItem -Path $logFolder -Filter "ray-*.log" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
