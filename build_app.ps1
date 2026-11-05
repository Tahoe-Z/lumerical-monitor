param(
    [string]$Python = 'python',
    [string]$OutputDirectory = 'dist'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath 'icon.ico')) {
    & $Python make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
}
& $Python -m PyInstaller --noconfirm --onedir --windowed --name LumericalMonitor --icon icon.ico --distpath $OutputDirectory --add-data 'remote_probe.py;.' --add-data 'preview_export.py;.' --add-data 'icon.ico;.' app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
$monitorOutput = Join-Path $OutputDirectory 'LumericalMonitor'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'profile.example.json') -Destination (Join-Path $monitorOutput 'profile.example.json')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination (Join-Path $monitorOutput 'LICENSE')
Write-Output (Join-Path $monitorOutput 'LumericalMonitor.exe')
