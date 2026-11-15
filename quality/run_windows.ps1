param(
    [switch]$Build,
    [switch]$RequireOracles
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows 11.' }
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
$previousQt = $env:QT_QPA_PLATFORM
try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Install Python 3.13 and .[dev,media,quality] in .venv first.' }
    $oracles = @('qpdf', 'exiftool', 'pdftotext', 'pdftoppm', 'pdfinfo', 'pdfdetach')
    $missing = @($oracles | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
    if ($missing.Count -gt 0) {
        $message = 'Missing independent readers: ' + ($missing -join ', ')
        if ($RequireOracles) { throw $message }
        Write-Warning ($message + '. Corresponding tests will report skips.')
    }
    New-Item -ItemType Directory -Force 'quality/results/windows' | Out-Null
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Lint failed.' }
    & $python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw 'Formatting failed.' }
    $env:QT_QPA_PLATFORM = 'offscreen'
    & $python -m pytest tests -q --timeout=60 --junitxml=quality/results/windows/tests.xml
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; inspect tests.xml.' }
    & $python benchmarks/benchmark_suite.py --cases import_app build_registry text100 scan20 image12mp qt_soak --heavy-runs 1 --soak-jobs 100 --report quality/results/windows/benchmarks.json
    if ($LASTEXITCODE -ne 0) { throw 'Benchmarks failed.' }
    if ($Build) {
        & ./packaging/build_windows.ps1
        if ($LASTEXITCODE -ne 0) { throw 'Windows package build failed.' }
    }
    Write-Output 'Automated checks finished. Review skips and complete the manual desktop checklist in quality/README.md.'
} finally {
    $env:QT_QPA_PLATFORM = $previousQt
    Pop-Location
}
