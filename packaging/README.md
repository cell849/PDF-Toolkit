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
and creates `dist/LocalPDFToolkit-Windows-x64.zip`. It does not publish anything.
It requires a 64-bit Python 3.13 environment and fails the self-test gate after
60 seconds rather than waiting indefinitely. The Actions workflow creates the
same `.venv` used by the local build script and runs lint, formatting and tests
before packaging.
GitHub Actions `Windows package` can also be run manually once this repository
is placed on GitHub. The successful run above is the recorded verification.

Extract the entire archive; keep `_internal` beside the executable. Launch
`LocalPDFToolkit.exe`. Python is bundled; LibreOffice is not. For Office → PDF,
install LibreOffice locally; other supported tools operate without it.

The archive is a portable folder, not an MSI/installer, signed binary or update
service. There are no automatic downloads, telemetry or cloud APIs.

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

Use https://github.com/cell849/tools/releases/latest and select the Windows ZIP
under Assets. Release assets are the app ZIP itself, so extraction is needed
only once. The source-code archives automatically listed by GitHub are not the app.
The private repository still requires GitHub sign-in.

To publish a new private release, manually run Windows package with a new
`release_tag` such as `v0.2.1`. A release is created only after tests, packaging
and the frozen-worker smoke check pass; existing releases are not overwritten.

## v0.7.0 identity and signing

The build embeds the original app ICO and product/version resources and includes
SVG/ICO/PNG UI artwork. Its self-test renders the real workspace, verifies bundled
artwork and performs a spawned conversion. A ZIP SHA-256 checksum is generated.

No trusted signing identity was provided. The package is unsigned; SmartScreen
or Smart App Control may warn/block according to the machine's policy. Neither
an app icon, version metadata, a self-signed certificate nor a checksum establishes
trusted publisher identity. Do not disable Windows protections as a build step.

For a future already-provisioned trusted Windows certificate, place SignTool on
PATH and pass `-SigningThumbprint <certificate-thumbprint>` to build_windows.ps1
(or set WINDOWS_SIGNING_THUMBPRINT). The script signs using SHA-256, requests an
RFC3161 timestamp, verifies Authenticode trust and only then creates the ZIP. A
requested but failed/untrusted signature stops the build. It never creates a
certificate, purchases a service or logs a private key. Hosted runners need their
own approved signing provisioning; this optional hook alone does not install it.
Signing can improve publisher identification but does not guarantee immediate
SmartScreen reputation. See Microsoft's current guidance:
https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation
