
# --------------------------------------------------
# AI JOB OUTREACH — SCHEDULED WORKFLOW
# --------------------------------------------------

$ErrorActionPreference = "Stop"

# Locate the project folder.
$ProjectDir = $PSScriptRoot

# Use the existing Python virtual environment.
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

# Main workflow entry point.
$MainScript = Join-Path $ProjectDir "main.py"

# Store execution logs.
$LogDir = Join-Path $ProjectDir "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Create a separate log for each execution.
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

$LogFile = Join-Path $LogDir "workflow_$Timestamp.log"

# Ensure Python can find the project's files.
Set-Location $ProjectDir

# Run Python through Windows cmd.exe.
# Redirect stdout and stderr directly to the log file.
# This avoids PowerShell interpreting Python warnings as errors.

$Command = '""{0}" -u "{1}" > "{2}" 2>&1"' -f `
    $Python, $MainScript, $LogFile

& cmd.exe /d /s /c $Command

# Capture the actual Python process exit code.
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Host "Workflow failed (exit code $ExitCode)."
    Write-Host "See log: $LogFile"
    exit $ExitCode
}

Write-Host "Workflow completed successfully."
Write-Host "Log: $LogFile"

exit 0