# 0.8 review

Reviewed v0.7.2 plus local polish commit 3474c10. Scope: file safety, privacy,
concurrency, measured performance, desktop UX, recent tools and packaging. Two
bounded Sol review agents covered privacy and backend safety; the main agent
reviewed their diffs, UI flows, measurements and release integration.

## Confirmed defects and fixes

- DOCX cleaning accepted document/write protection, retaining hash/salt attributes,
  and missed `webHidden` text. These inputs now fail clearly before publication.
- ODF cleanup missed relative external-workbook formula references, retaining private
  source paths. Reject these references while preserving local formulas.
- PPTX cleaning accepted non-whitespace XML tail text and malformed relationship
  text/children. These structures now fail closed rather than leaking hidden text.
- An Office supervisor that exited before its child left a live descendant on
  POSIX. Always clean its process group; taskkill errors now allow Windows fallback
  termination. Native Windows descendant lifetime after supervisor exit remains
  a separate limitation; no cross-platform process-tree guarantee is claimed.
- HEIC metadata inspection used Pillow’s HEIF name as an unsupported format enum.
  Normalize it through the existing codec/format mapping; real HEIC regression added.
- Malformed ZIP Office input in batch rename surfaced as a generic error. It now
  receives invalid-input classification; batch rollback and originals are preserved.
- Each inspection completion rebuilt the entire file list. Update the affected
  row when its identity still matches; structural changes retain full rebuilds.
- An invalid selected file displayed “Add a file” in the preview. It now says
  preview is unavailable; pending inspection has its own message.
- Capability documentation still described preset-only DPI, KiB-only targeting
  and default downscaling. Corrected against registered options and UI behavior.

## Evidence

Concrete negative fixtures precede privacy/process fixes. Existing tests cover
exclusive publication, injected publication failures, collisions, cancellation,
source hashes, input/output mapping, retries, process shutdown and optional-engine
absence. UI workflows exercise actual spawned inspection/conversion/preview jobs,
QTest input, tool switching, partial failure and recovery. Batch-name preview/save
comparisons use exact names and byte equality. Selected-result opening verifies
its dispatched path; external viewer behavior is not established by that test.
Document-detail tests check locked PDFs, dimension orientation, structural limits
and report disclosure. New assertions target demonstrated failures, not counts.

Full Linux regression run: 572 passed in 126.42 seconds. The final HEIC-focused
module rerun passed all 9 tests. Lint, formatting and whitespace checks passed.
Windows results are available in the v0.8.0 release workflow.
`packaging/verify_ui.py` reruns these workflows and captures synthetic rendered
end states. The Windows workflow additionally uses the native Qt platform at 150%
scale. Existing theme/layout checks cover both palettes, narrow windows and 200%
app text. Screenshots were inspected for clipping, focus, name-plan alignment,
error prominence and preview state; image existence alone is not the test oracle.

## Performance

`benchmarks/v08-linux.json` records seven startup/image samples and three 100-job
preview/cancellation soaks. Import median 0.120 s; registry 0.164 s; 12 MP image
conversion 0.356 s. Soaks completed 50 jobs and cancelled 50 each, with no live job
process afterward; one multiprocessing resource tracker remained. Parent RSS grew
0.29–0.39 MiB during each soak. Some samples overlapped review tests: heartbeat
p95 varied 5.6–33.8 ms, so these are diagnostic observations, not controlled
before/after speed comparisons or Windows timings.

Focused list-refresh measurement: at 10,000 synthetic local files, the former full
refresh took 208 ms; seven incremental updates took 1.68–2.01 ms. See
`benchmarks/v08-list-refresh.json`. This measures row updates, not full batch
inspection time. No conversion speedup or universal leak-free claim is made.
Separate file-tools measurements assess validation parsing and copying; no unsafe
validation bypass was introduced to improve those timings.

## Design and test judgment

Apple skill `references/hig/layout.md`, **Visual hierarchy**, says “Group related
items to clearly express related information or functions” and “Use progressive
disclosure to make layouts cleaner and easier to interact with.” Grouped menus,
contextual preview controls and quieter idle chrome follow that guidance. The
invalid-file prompt was a usability defect. Badge styling, headline size and
reduced slogans are subjective polish choices, not mandatory HIG rules. Existing
Windows menus, shortcuts, focus and window controls are retained. No new effects,
features or runtime dependencies were introduced.

The previous test audit had already removed trivial fixture/Qt-class assertions.
This review retained similar-looking tests where formats, lifecycle boundaries
or independent readers differ. Test quantity is not a performance cost in normal
application use. We did not delete safety checks simply to reduce the count.

## Remaining limits

A controlled child calling `os._exit(7)` inside OutputTransaction left a hidden
`.pdf-toolkit-*` directory containing its incomplete staged file. Cooperative
cancellation cleans up; hard crashes cannot execute Python cleanup. Automatic
cross-session deletion would require trustworthy ownership information and was
not added speculatively. No originals or pre-existing output were altered in the
reproduction. Atomic file publication does not imply crash-atomic multi-file batches.

Independent synthetic matrix: 17 cleanups, source SHA-256 unchanged and no injected
canary in outputs/reports. ExifTool read image/PDF/RTF metadata; ffprobe checked
media streams/tags; qpdf/Poppler validated PDFs. Office packages used separate
stdlib ZIP/XML inspection because this environment lacks ExifTool Archive::Zip.

Metadata cleaning is not anonymization: visible text/images and audible content
can identify people. Independent reader checks sample defined formats and fields;
they cannot prove every possible payload absent. Reports explicitly describe
structural bounds and metadata/content distinctions.

This Linux environment lacks an exposed interactive desktop tool. Automated Qt
workflows and rendered captures were used; no human Windows desktop session was
performed. Native Windows runner checks do not replace physical display scaling,
keyboard/screen-reader usability, external default-app opening, clean-machine
optional-engine installation, or first-time-user testing. The binary is unsigned;
checksums do not remove SmartScreen reputation warnings.
