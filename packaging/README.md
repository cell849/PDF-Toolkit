# Windows packaging (M4)

M5 Office functionality and its real-engine tests were completed before this
packaging setup, as requested. The Windows executable has now been built and
its spawned-worker self-test verified through GitHub Actions:

https://github.com/cell849/tools/actions/runs/43655035967

Download the `LocalPDFToolkit-Windows-x64` artifact (GitHub sign-in required),
extract the downloaded artifact ZIP, then extract its enclosed Windows ZIP.
Launch `LocalPDFToolkit/LocalPDFToolkit.exe` with the `_internal` folder beside it.
Actions artifacts expire; the source/build workflow remains in the repository.
Actual Windows 11 manual desktop and LibreOffice validation is still required.

To build again, run the workflow or the following local instructions on Windows.

On Windows 11 with 64-bit Python 3.13, follow root README.md to install `.[dev]`,
then run from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build_windows.ps1
```

This process-scoped execution policy does not change the machine policy.
The script builds an onedir executable, runs its real spawned-worker self-test,
and creates `dist/PDFToolkit.zip`. It does not publish anything.
It requires a 64-bit Python 3.13 environment and fails the self-test gate after
60 seconds rather than waiting indefinitely. The Actions workflow creates the
same `.venv` used by the local build script and runs lint, formatting and tests
before packaging.
GitHub Actions `Windows package` can also be run manually once this repository
is placed on GitHub. The successful run above is the recorded verification.

Extract the entire archive; keep `_internal` beside the executable. Launch
`PDFToolkit.exe`. Python is bundled; LibreOffice is not. For Office → PDF,
install LibreOffice locally; other supported tools operate without it.

The archive is a portable folder, not an MSI/installer or update service.
Signing is optional as described below. There are no automatic downloads,
telemetry or cloud APIs.

Clean Windows 11 verification still required:

1. Run with no development Python installed; launch, resize and close the window.
2. Convert PDF → images and ordered images → PDF; merge/extract a sample.
3. Check cancel/retry, output collisions, non-ASCII filenames and an NTFS folder.
4. Check target-size outputs actually stay below the requested KiB limit.
5. Without LibreOffice, verify the helpful dependency error; then install it and
   test DOCX/XLSX/PPTX and representative OpenDocument files with local fonts.
6. Run the executable with `--self-test` and check its process exit code.
7. Repeat normal use with network disconnected. Verify printing/viewing in local
   software as appropriate; compare Office pagination with the original.

Linux packaging smoke tests establish that PyInstaller bundles importable
modules/data and supports worker spawning on Linux. They do not establish
Windows DLL discovery, Windows process-tree cancellation, font fidelity,
SmartScreen behavior or clean-machine compatibility.

See THIRD_PARTY.md before any redistribution.

## Simplified download

Use https://github.com/cell849/PDF-Toolkit/releases/latest and select the Windows ZIP
under Assets. Release assets are the app ZIP itself, so extraction is needed
only once. The source-code archives automatically listed by GitHub are not the app.
The private repository still requires GitHub sign-in.

To publish a new private release, manually run Windows package with a new
`release_tag` such as `v0.2.1`. A release is created only after tests, packaging
and the frozen-worker smoke check pass; existing releases are not overwritten.

## Identity and signing

The build embeds the original app ICO and product/version resources and includes
SVG/ICO/PNG UI artwork. Its self-test renders the real workspace, verifies bundled
artwork and performs a spawned conversion. A ZIP SHA-256 checksum is generated.

Choose `signing_mode: self-signed` when manually running `Windows package` to
produce a self-signed app. Leave `release_tag` empty to build a downloadable
Actions artifact without publishing a release. The workflow default remains
`unsigned`; signed and unsigned builds both run the frozen-worker self-test.
Self-signed signing checks the executable's integrity but does not establish a
trusted publisher. Windows SmartScreen or Smart App Control can still warn or
block it according to machine policy. Do not disable Windows protections.

For a local Windows build with the Windows SDK installed:

```powershell
powershell -NoProfile -File packaging/build_windows.ps1 -SigningMode self-signed
```

SignTool is discovered on PATH or in the installed Windows SDK's versioned x64
directory. Self-signed mode creates an RSA-3072/SHA-256 code-signing certificate
in `Cert:\CurrentUser\My` with a non-exportable private key and three-year
validity. Later local builds reuse this certificate until it approaches expiry.
To choose an existing self-signed identity, also pass `-SigningThumbprint`.
The public certificate goes in the ZIP; the private key stays in the Windows
certificate store and is never exported or uploaded. No certificate is added to
Trusted Root or Trusted Publishers.

Hosted Actions builds use `-EphemeralSelfSignedCertificate`: a fresh identity is
created for each run, then its certificate and private key are removed in a
`finally` block. These builds have different certificate fingerprints across runs
and do not provide a persistent publisher identity. No signing secret is required.
Self-signed signatures are not timestamped; they expire with their certificate.

Every signed ZIP includes `PDFToolkit-signing.cer`, `SIGNATURE.txt` (public
certificate SHA-256 fingerprint and SHA-1 thumbprint identifier), and
`Verify-Signature.ps1`. Inspect the script, then from the extracted app folder run:

```powershell
powershell -NoProfile -File .\Verify-Signature.ps1
Get-FileHash .\PDFToolkit-signing.cer -Algorithm SHA256
```

The verifier checks the PKCS#7 signature cryptographically, matches the signer to
the public certificate and uses Windows Authenticode to verify the executable's
digest. Self-signed mode permits Windows' untrusted-root result, while rejecting
other errors such as a changed executable. It makes no network requests and
does not install certificates. The workflow additionally modifies a copy of the
signed EXE and requires verification to reject it with `TRUST_E_BAD_DIGEST`.
Compare certificate fingerprints against a separately trusted source if publisher
identity matters; a certificate and fingerprint supplied in the same ZIP do not
authenticate its producer. The ZIP's `.sha256` file checks download integrity.

For an already-provisioned trusted Windows certificate in `CurrentUser\My`, pass
`-SigningMode trusted -SigningThumbprint <certificate-thumbprint>` (passing only
`-SigningThumbprint`, or setting `WINDOWS_SIGNING_THUMBPRINT`, retains the existing
trusted-signing behavior). This mode uses SHA-256, requests an RFC3161 timestamp,
and requires trusted Authenticode verification before packaging. Its bundled
verifier needs `-SigningMode trusted`; receiving-machine trust policy can differ.
A requested but failed signature stops the build. Hosted runners need separate
approved provisioning for a trusted identity; the dispatch choices do not
provision one. Signing does not guarantee immediate SmartScreen reputation.
See Microsoft's current guidance:
https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation
