param([string]$SigningThumbprint = $env:WINDOWS_SIGNING_THUMBPRINT)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not $IsWindows -and $env:OS -ne 'Windows_NT') {
        throw 'Build the Windows app on Windows with 64-bit Python 3.13.'
    }
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Create .venv and install .[dev,media] first; see README.md.' }
    & $python -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Use a 64-bit Python 3.13 virtual environment.' }
    & $python -m PyInstaller --noconfirm --clean --windowed --onedir --name LocalPDFToolkit `
        --collect-all docx --collect-all pptx --collect-all openpyxl --hidden-import pillow_heif `
        --additional-hooks-dir packaging/hooks `
        --icon src/local_pdf_toolkit/ui/assets/icons/app.ico --version-file packaging/version_info.txt `
        --add-data "src/local_pdf_toolkit/ui/assets/icons:local_pdf_toolkit/ui/assets/icons" `
        --add-data 'CAPABILITIES.md:.' --add-data 'packaging/THIRD_PARTY.md:.' packaging/launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $app = Join-Path $projectRoot 'dist\LocalPDFToolkit\LocalPDFToolkit.exe'
    if ($SigningThumbprint) {
        $tool = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if (-not $tool) { throw 'Signing requested but SignTool is not available on PATH.' }
        & $tool.Source sign /sha1 $SigningThumbprint /fd SHA256 /tr https://timestamp.digicert.com /td SHA256 $app
        if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed.' }
        & $tool.Source verify /pa /all $app
        if ($LASTEXITCODE -ne 0) { throw 'Signature verification failed.' }
        if ((Get-AuthenticodeSignature $app).Status -ne 'Valid') { throw 'A trusted signature is required.' }
    } else {
        Write-Output 'No signing identity configured. SmartScreen may warn about this unsigned app.'
    }
    $test = Start-Process -FilePath $app -ArgumentList '--self-test' -PassThru
    # Bound the packaging gate even if a native converter cannot cancel promptly.
    $null = $test.Handle
    if (-not $test.WaitForExit(60000)) {
        & taskkill /PID $test.Id /T /F
        throw 'Packaged worker self-test exceeded 60 seconds.'
    }
    if ($test.ExitCode -ne 0) { throw 'Packaged worker self-test failed.' }
    Compress-Archive -Path 'dist\LocalPDFToolkit' -DestinationPath 'dist\LocalPDFToolkit-Windows-x64.zip' -Force
    $archive = 'dist\LocalPDFToolkit-Windows-x64.zip'
    $hash = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()
    "$hash  LocalPDFToolkit-Windows-x64.zip" | Set-Content -Encoding ascii 'dist\LocalPDFToolkit-Windows-x64.zip.sha256'
    Write-Output 'Built dist\LocalPDFToolkit-Windows-x64.zip; clean-machine verification remains required.'
} finally {
    Pop-Location
}
