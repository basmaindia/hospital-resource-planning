# PowerShell compilation script for the academic report
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Convert Windows path to WSL path
$wslPath = $scriptDir -replace '\\', '/' -replace '^[A-Za-z]:', { "/mnt/" + $_.Value.Substring(0,1).ToLower() }

Write-Host "Compilation du rapport académique dans WSL..." -ForegroundColor Cyan
wsl -d Ubuntu -e /bin/bash -c "cd '$wslPath' && ./compile.sh"

if (Test-Path "$scriptDir\main.pdf") {
    Write-Host "`nRapport compilé avec succès :" -ForegroundColor Green
    Write-Host "  -> $scriptDir\main.pdf" -ForegroundColor Green
} else {
    Write-Host "`nErreur lors de la compilation du PDF." -ForegroundColor Red
}
