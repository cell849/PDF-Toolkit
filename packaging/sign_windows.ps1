param(
    [Parameter(Mandatory = $true)][string]$AppPath,
    [Parameter(Mandatory = $true)][ValidateSet('self-signed', 'trusted')][string]$SigningMode,
    [string]$SigningThumbprint = $env:WINDOWS_SIGNING_THUMBPRINT,
    [switch]$EphemeralSelfSignedCertificate
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Windows code signing requires Windows.' }
if ($EphemeralSelfSignedCertificate -and ($SigningMode -ne 'self-signed' -or $SigningThumbprint)) {
    throw 'Ephemeral mode only supports a newly generated self-signed certificate.'
}
$tool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($tool) { $signTool = $tool.Source }
else {
    $sdkRoots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles) | Where-Object { $_ } | Select-Object -Unique
    $candidates = foreach ($root in $sdkRoots) {
        Get-ChildItem -Path (Join-Path $root 'Windows Kits\10\bin\*\x64\signtool.exe') -ErrorAction SilentlyContinue
    }
    $signTool = $candidates | Sort-Object { [version]$_.Directory.Parent.Name } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $signTool) { throw 'Signing requires SignTool from the Windows SDK (PATH or Windows Kits\10\bin).' }
}
$createdCertificate = $null
try {
    $friendlyName = 'Local PDF Toolkit self-signed code signing'
    if ($SigningThumbprint) {
        $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$SigningThumbprint"
    } elseif ($SigningMode -eq 'trusted') {
        throw 'Trusted signing requires -SigningThumbprint (or WINDOWS_SIGNING_THUMBPRINT).'
    } else {
        $certificate = $null
        if (-not $EphemeralSelfSignedCertificate) {
            $certificate = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
                $_.FriendlyName -eq $friendlyName -and $_.HasPrivateKey -and
                $_.Subject -eq $_.Issuer -and $_.NotAfter -gt (Get-Date).AddDays(30) -and
                ($_.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.3')
            } | Sort-Object NotAfter -Descending | Select-Object -First 1
        }
        if (-not $certificate) {
            $certificate = New-SelfSignedCertificate -Type CodeSigningCert `
                -Subject 'CN=Local PDF Toolkit (Self-Signed)' -FriendlyName $friendlyName `
                -CertStoreLocation Cert:\CurrentUser\My -KeyAlgorithm RSA -KeyLength 3072 `
                -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -KeyUsage DigitalSignature `
                -NotAfter (Get-Date).AddYears(3)
            $createdCertificate = $certificate
        }
    }
    if (-not $certificate.HasPrivateKey) { throw 'The signing certificate has no accessible private key.' }
    if ($SigningMode -eq 'self-signed' -and $certificate.Subject -ne $certificate.Issuer) {
        throw 'Self-signed mode requires a self-issued certificate.'
    }
    $arguments = @('sign', '/s', 'My', '/sha1', $certificate.Thumbprint, '/fd', 'SHA256')
    if ($SigningMode -eq 'trusted') { $arguments += @('/tr', 'https://timestamp.digicert.com', '/td', 'SHA256') }
    & $signTool @arguments $AppPath
    if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed.' }
    if ($SigningMode -eq 'trusted') {
        & $signTool verify /pa /all $AppPath
        if ($LASTEXITCODE -ne 0 -or (Get-AuthenticodeSignature $AppPath).Status -ne 'Valid') {
            throw 'A valid trusted Authenticode signature is required.'
        }
    }
    $directory = Split-Path $AppPath -Parent
    $publicCertificate = Join-Path $directory 'LocalPDFToolkit-signing.cer'
    $null = Export-Certificate -Cert $certificate -FilePath $publicCertificate -Type CERT
    $verifier = Join-Path $PSScriptRoot 'verify_windows_signature.ps1'
    & $verifier -AppPath $AppPath -CertificatePath $publicCertificate -SigningMode $SigningMode
    Copy-Item -LiteralPath $verifier -Destination (Join-Path $directory 'Verify-Signature.ps1') -Force
    $certificateHash = (Get-FileHash -LiteralPath $publicCertificate -Algorithm SHA256).Hash
    $identity = if ($SigningMode -eq 'self-signed') {
        'Self-signed: Windows does not trust this publisher by default. SmartScreen warnings can remain.'
    } else { 'Trusted signing was verified by the build machine; receiving-machine policy may differ.' }
    @"
Local PDF Toolkit Authenticode signature
Mode: $SigningMode
$identity
Certificate SHA-256: $certificateHash
Certificate thumbprint (SHA-1 identifier): $($certificate.Thumbprint)
Certificate expires: $($certificate.NotAfter.ToUniversalTime().ToString('u'))

The .cer contains only the public certificate. No private key is distributed.
From this extracted folder in Windows PowerShell, verify with:
powershell -NoProfile -File .\Verify-Signature.ps1 -SigningMode $SigningMode
Inspect the script first; your existing PowerShell execution policy still applies.
Verification checks the embedded signature, executable digest and matching public certificate.
For self-signed mode, it permits only Windows' untrusted-root error, never a digest failure.
Compare the certificate SHA-256 above against a separately trusted source before relying on publisher identity.
Files/fingerprints supplied together cannot establish the identity of their producer.
Do not install this certificate into Trusted Root or disable Windows protections for verification.
Self-signed signatures have no timestamp and expire with their certificate.
"@ | Set-Content -LiteralPath (Join-Path $directory 'SIGNATURE.txt') -Encoding utf8
} finally {
    if ($EphemeralSelfSignedCertificate -and $createdCertificate) {
        Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($createdCertificate.Thumbprint)" -DeleteKey -Force
    }
}
