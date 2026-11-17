# Inspector and control polish after 0.8.1

Implemented locally for review. No push, release or new executable publication.
The existing release is unchanged. No runtime dependencies, fonts or downloaded
icon packs were added; navigation symbols are original Qt-drawn icons.

## What changed and how

- The right inspector is a short rail of Options, Advanced (when relevant) and
  Save copy dropdowns. Their anchored popovers are measured from content and screen
  bounds. The rail itself never scrolls. Oversized content can scroll inside an
  opened popover on small screens/enlarged text instead of overlapping or clipping.
- Replaced long requirement/policy paragraphs with info buttons. Hover shows help;
  click or Space opens a wrapping, selectable explanation. Accessible names and full
  descriptions remain available. Each setting has contextual help. Engine warnings
  on library cards also moved to info buttons. Actual conversion errors remain
  prominent in the result banner.
- Form labels and fields are measured independently with consistent spacing.
  Composite controls keep enough height when they stack. Custom page sizes and
  mode-dependent settings remain available without squeezing the next row.
- Dropdowns use sentence-case captions while preserving converter data values.
  Long paper names determine popup width. All pages is a placeholder whose getter
  still returns the existing `all` value. Simple tools no longer require Advanced
  merely to reach their only option.
- Choice popups explicitly inherit the field palette/font; their separate window
  previously stayed white in dark mode. Rounded frame/list items and a native
  rounded mask are applied to the actual popup container.
- Sliders have a thin filled track, light round thumb and round focus indication.
  Exact typing, keyboard stepping and landmark snapping are retained. A reproduced
  bug where slider gestures changed the number but not the summary was fixed with
  one composite valueChanged notification; the usual settings/stale-result path
  now runs for both gestures and typed values.
- Sidebar can collapse using its visible button or Ctrl+B/View. Category symbols,
  tooltips, selection and accessible names remain in a 64px rail; expanding restores
  labels. Preference persists, and narrow windows default to compact navigation.
- Removed the processing slogan, repeated originals/idle instructions, inline size
  unit prose and automatic-extension boilerplate. Useful settings summaries and
  error/recovery messages remain. Layout/focus recovery opens the relevant dropdown.

## Design guidance applied

Read the installed Apple design skill and relevant references. `layout.md`, Visual
hierarchy: “Align elements to make them easier to scan” informs the measured rows.
`disclosure-controls.md`, Best practices: “Use a disclosure control to hide details
until they’re relevant” informs the inspector. `sliders.md` describes the filled
track and supplementary exact entry. `sidebars.md` motivates compact navigation
when space is limited. Accessibility, typography, color, macOS/cross-platform and
pop-up-button references also informed readable text and keyboard help. These are
Qt/Windows adaptations, not a macOS replica or a full compliance certification.

## Verification and limits

The full Linux regression gate passed **686 tests in 127.69 seconds**. The final
mixed UI run passed **35 tests** after the last responsive target-unit refinement.
This includes typed/dragged values, all tool forms, bounds/spacing at 100% and 200%,
light/dark and narrow/wide windows (including percentage targets and custom sizes).
Lint, format and whitespace checks passed. Source `--self-test` passed.

Existing layout tests now open the relevant dropdown before inspecting fields;
assertions were retained. New tests cover actual open-menu palette/font/keyboard
selection, field geometry for every tool, and icon-only navigation. Fixed test
preference isolation so the named QSettings constructor cannot leak saved units
between tests or touch a Windows user's real preference store. No conversion/backend
logic was changed, and no tests were removed.

These are rendered Linux Qt checks. This turn did not run a native Windows build or
publish a branch. Offscreen Qt cannot validate the native rounded-window mask;
Windows display scaling, screen-reader behavior and native popup edges still need
verification before release. Tall popovers deliberately retain a scroll fallback.

## Rendered examples

- [Collapsed workspace, dark](inspector-review/workspace-dark.png)
- [Workspace, light](inspector-review/workspace-light.png)
- [Page-size settings](inspector-review/options-dark.png)
- [Open choice menu](inspector-review/dropdown-dark.png)
- [Sliders](inspector-review/sliders-dark.png)
- [Enlarged text](inspector-review/large-text.png)

The images are synthetic UI captures under docs and are not bundled into the app.
