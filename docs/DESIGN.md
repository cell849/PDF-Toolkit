# Desktop design — v0.3.0

The single job is to find a document tool and complete it locally. Its signature
is a library of small paper-like cards with format badges, leading to one focused
workspace. This adopts Apple hierarchy and spacing with Qt widgets, Windows
window controls, system typography, menus and keyboard conventions. It does not
imitate macOS window decorations or use Apple font/symbol assets.

References read from apple-design: accessibility.md (Vision), layout.md (Visual
hierarchy), typography.md (Ensuring legibility), color.md (Best practices),
designing-for-macos.md, sidebars.md, buttons.md (Best practices/Style),
search-fields.md (Best practices), and cross-platform.md. For example, layout.md
says “Group related items to clearly express related information or functions”;
buttons.md says “Always include a press state for a custom button.” Grouped Qt
panels, explicit button states and keyboard focus implement those principles.

Semantic light/dark tokens in ui/design.py: canvas, sidebar, surface, text,
secondary, border, accent and selection. Body is system-family 13px; section 17px;
display 30px; small utility labels 11px. No bundled font or animation is required.
Opaque surfaces work without blur or transparency settings. System color-scheme
changes select the palette. Higher contrast OS settings, screen readers and
Windows text scaling require real Windows accessibility verification.

Regular: category sidebar | searchable 3-column library → focused workspace.
Compact (760×620): resizable/hideable sidebar | 1-column library; workspace form
labels wrap above fields, file actions wrap, body scrolls while feedback/actions
remain fixed. Ctrl+O imports, Ctrl+F searches, Ctrl+Return runs; Alt+Left returns
to the library and Ctrl+B toggles the sidebar. Menus expose tools and queue actions.
Navigation cannot hide the cancel action while a conversion is active.

Deliberate restraint: no fake glass, animations, account prompts, or decorative
window controls. All 28 converters and existing worker/transaction behavior remain.

Measured WCAG contrast on panel surfaces: secondary light #606574/white 5.82:1,
primary light #1d1d1f/white 16.83:1, blue action #005bb5/white 6.64:1;
dark secondary #b8bcc7/#292b31 7.45:1 and primary #f5f5f7/#292b31 12.99:1.
These text pairs exceed the 4.5:1 small-text threshold; this is not a full
accessibility certification. Visible focus, system-theme changes and resizing
are implemented; real Windows scaling/screen-reader testing remains manual.
