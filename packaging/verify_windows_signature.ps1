param(
    [string]$AppPath = (Join-Path $PSScriptRoot 'PDFToolkit.exe'),
    [string]$CertificatePath = (Join-Path $PSScriptRoot 'PDFToolkit-signing.cer'),
    [ValidateSet('self-signed', 'trusted')][string]$SigningMode = 'self-signed'
)
$ErrorActionPreference = 'Stop'

# WinVerifyTrust validates the Authenticode digest against the actual PE file.
# SignedCms separately verifies the embedded PKCS#7 signature without chain trust.
if (-not ('LocalPDFToolkit.SignatureTrust' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace LocalPDFToolkit {
    public static class SignatureTrust {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct FileInfo {
            public uint Size;
            [MarshalAs(UnmanagedType.LPWStr)] public string Path;
            public IntPtr File;
            public IntPtr KnownSubject;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct TrustData {
            public uint Size;
            public IntPtr PolicyCallback;
            public IntPtr SipClient;
            public uint UiChoice;
            public uint RevocationChecks;
            public uint UnionChoice;
            public IntPtr FileInfo;
            public uint StateAction;
            public IntPtr StateData;
            public IntPtr UrlReference;
            public uint ProviderFlags;
            public uint UiContext;
        }
        [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);
        public static int Verify(string path) {
            var info = new FileInfo { Size = (uint)Marshal.SizeOf(typeof(FileInfo)), Path = path };
            IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(FileInfo)));
            Marshal.StructureToPtr(info, pointer, false);
            var data = new TrustData {
                Size = (uint)Marshal.SizeOf(typeof(TrustData)), UiChoice = 2,
                UnionChoice = 1, FileInfo = pointer, StateAction = 1,
                ProviderFlags = 0x1010 // Cache-only retrieval, no revocation network requests.
            };
            var action = new Guid("00AAC56B-CD44-11D0-8CC2-00C04FC295EE");
            try { return WinVerifyTrust(IntPtr.Zero, ref action, ref data); }
            finally {
                data.StateAction = 2;
                WinVerifyTrust(IntPtr.Zero, ref action, ref data);
                Marshal.DestroyStructure(pointer, typeof(FileInfo));
                Marshal.FreeHGlobal(pointer);
            }
        }
    }
}
'@
}
if (-not ('System.Security.Cryptography.Pkcs.SignedCms' -as [type])) {
    Add-Type -AssemblyName System.Security
}
if (-not ('System.Security.Cryptography.Pkcs.SignedCms' -as [type])) {
    Add-Type -AssemblyName System.Security.Cryptography.Pkcs
}
$AppPath = (Resolve-Path -LiteralPath $AppPath).Path
$CertificatePath = (Resolve-Path -LiteralPath $CertificatePath).Path
$certificate = New-Object -TypeName System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList $CertificatePath
try {
    $bytes = [System.IO.File]::ReadAllBytes($AppPath)
    if ($bytes.Length -lt 64 -or [BitConverter]::ToUInt16($bytes, 0) -ne 0x5A4D) { throw 'Not a Windows PE executable.' }
    $pe = [BitConverter]::ToInt32($bytes, 60)
    if ($pe -lt 64 -or $pe + 152 -gt $bytes.Length -or [BitConverter]::ToUInt32($bytes, $pe) -ne 0x4550) {
        throw 'Invalid PE header.'
    }
    $optionalHeader = $pe + 24
    $magic = [BitConverter]::ToUInt16($bytes, $optionalHeader)
    if ($magic -eq 0x20B) { $directories = $optionalHeader + 112 }
    elseif ($magic -eq 0x10B) { $directories = $optionalHeader + 96 }
    else { throw 'Unsupported PE optional header.' }
    $entry = $directories + 32 # IMAGE_DIRECTORY_ENTRY_SECURITY (file offset, not RVA).
    $offset = [BitConverter]::ToUInt32($bytes, $entry)
    $size = [BitConverter]::ToUInt32($bytes, $entry + 4)
    if ($size -lt 8 -or [long]$offset + $size -gt $bytes.Length) { throw 'Missing or invalid Authenticode signature.' }
    $length = [BitConverter]::ToUInt32($bytes, $offset)
    if ($length -lt 8 -or $length -gt $size -or [BitConverter]::ToUInt16($bytes, $offset + 6) -ne 2) {
        throw 'Invalid Authenticode certificate entry.'
    }
    $encoded = New-Object byte[] ($length - 8)
    [Array]::Copy($bytes, $offset + 8, $encoded, 0, $encoded.Length)
    $cms = New-Object System.Security.Cryptography.Pkcs.SignedCms
    $cms.Decode($encoded)
    if ($cms.SignerInfos.Count -ne 1) { throw 'Expected exactly one Authenticode signer.' }
    $cms.CheckSignature($true)
    if ($cms.SignerInfos[0].Certificate.Thumbprint -ne $certificate.Thumbprint) {
        throw 'The executable signer does not match the supplied public certificate.'
    }
    if ($SigningMode -eq 'self-signed' -and $certificate.Subject -ne $certificate.Issuer) {
        throw 'Self-signed mode requires a self-issued certificate.'
    }
    $status = [LocalPDFToolkit.SignatureTrust]::Verify($AppPath)
    # CERT_E_UNTRUSTEDROOT is expected for an intact, untrusted self-signed app.
    # All other failures (including TRUST_E_BAD_DIGEST) stop verification.
    $untrustedRoot = -2146762487
    if ($status -ne 0 -and -not ($SigningMode -eq 'self-signed' -and $status -eq $untrustedRoot)) {
        throw ('Authenticode file verification failed: 0x{0:X8}.' -f $status)
    }
    if ($SigningMode -eq 'self-signed') {
        Write-Output 'Signature and executable digest verified. Self-signed certificate: no trusted publisher identity is established.'
    } else {
        Write-Output 'Signature, executable digest and Windows certificate trust verified (cached trust; no revocation network request).'
    }
    Write-Output ('Certificate SHA-256: ' + (Get-FileHash -LiteralPath $CertificatePath -Algorithm SHA256).Hash)
    Write-Output ('Certificate thumbprint (SHA-1 identifier): ' + $certificate.Thumbprint)
} finally {
    $certificate.Dispose()
}
