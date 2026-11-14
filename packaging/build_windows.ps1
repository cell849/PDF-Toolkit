$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not $IsWindows -and $env:OS -ne 'Windows_NT') {
        throw 'Build the Windows app on Windows with 64-bit Python 3.13.'
    }
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Create .venv and install .[dev] first; see README.md.' }
    & $python -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Use a 64-bit Python 3.13 virtual environment.' }
    & $python -m PyInstaller --noconfirm --clean --windowed --onedir --name LocalPDFToolkit `
        --collect-all docx --collect-all pptx --collect-all openpyxl `
        --add-data 'CAPABILITIES.md:.' --add-data 'packaging/THIRD_PARTY.md:.' packaging/launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $app = Join-Path $projectRoot 'dist\LocalPDFToolkit\LocalPDFToolkit.exe'
    $test = Start-Process -FilePath $app -ArgumentList '--self-test' -PassThru
    # Bound the packaging gate even if a native converter cannot cancel promptly.
    $null = $test.Handle
    if (-not $test.WaitForExit(60000)) {
        & taskkill /PID $test.Id /T /F
        throw 'Packaged worker self-test exceeded 60 seconds.'
    }
    if ($test.ExitCode -ne 0) { throw 'Packaged worker self-test failed.' }
    Compress-Archive -Path 'dist\LocalPDFToolkit' -DestinationPath 'dist\LocalPDFToolkit-Windows-x64.zip' -Force
    Write-Output 'Built dist\LocalPDFToolkit-Windows-x64.zip; clean-machine verification remains required.'
} finally {
    Pop-Location
}
