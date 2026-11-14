# Windows packaging (M4)

M5 Office functionality and its real-engine tests were completed before this
packaging setup, as requested. This cloud workspace is Linux: a Windows executable
cannot be built or verified here. The workflow below must run on Windows.

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
is placed on GitHub; no workflow run is implied by creating the YAML file.

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
