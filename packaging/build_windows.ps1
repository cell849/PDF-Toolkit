param(
    [string]$SigningThumbprint = $env:WINDOWS_SIGNING_THUMBPRINT,
    [ValidateSet('unsigned', 'self-signed', 'trusted')]
    [string]$SigningMode = $(if ($env:WINDOWS_SIGNING_THUMBPRINT) { 'trusted' } else { 'unsigned' }),
    [switch]$EphemeralSelfSignedCertificate
)
$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('SigningMode') -and $SigningThumbprint) { $SigningMode = 'trusted' }
if ($SigningMode -eq 'unsigned' -and ($SigningThumbprint -or $EphemeralSelfSignedCertificate)) {
    throw 'Unsigned mode cannot use a signing certificate.'
}
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
    & $python -m PyInstaller --noconfirm --clean --windowed --onedir --name PDFToolkit `
        --collect-all docx --collect-all pptx --collect-all openpyxl --hidden-import pillow_heif `
        --additional-hooks-dir packaging/hooks `
        --icon src/local_pdf_toolkit/ui/assets/icons/app.ico --version-file packaging/version_info.txt `
        --add-data "src/local_pdf_toolkit/ui/assets/icons:local_pdf_toolkit/ui/assets/icons" `
        --add-data 'CAPABILITIES.md:.' --add-data 'packaging/THIRD_PARTY.md:.' packaging/launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $app = Join-Path $projectRoot 'dist\PDFToolkit\PDFToolkit.exe'
    if ($SigningMode -ne 'unsigned') {
        & (Join-Path $PSScriptRoot 'sign_windows.ps1') -AppPath $app -SigningMode $SigningMode `
            -SigningThumbprint $SigningThumbprint -EphemeralSelfSignedCertificate:$EphemeralSelfSignedCertificate
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
    Copy-Item -LiteralPath 'LICENSE' -Destination 'dist\PDFToolkit\LICENSE.txt'
    Copy-Item -LiteralPath 'packaging\THIRD_PARTY.md' -Destination 'dist\PDFToolkit\THIRD_PARTY.md'
    Copy-Item -LiteralPath 'packaging\licenses' -Destination 'dist\PDFToolkit\licenses' -Recurse
    & $python packaging/collect_licenses.py 'dist\PDFToolkit\licenses\python-packages'
    if ($LASTEXITCODE -ne 0) { throw 'Could not collect dependency license notices.' }
    Compress-Archive -Path 'dist\PDFToolkit' -DestinationPath 'dist\PDFToolkit.zip' -Force
    $archive = 'dist\PDFToolkit.zip'
    $hash = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()
    "$hash  PDFToolkit.zip" | Set-Content -Encoding ascii 'dist\PDFToolkit.zip.sha256'
    Write-Output 'Built dist\PDFToolkit.zip; clean-machine verification remains required.'
} finally {
    Pop-Location
}
