import os
import subprocess
import sys

import pytest

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow
from local_pdf_toolkit.ui.start_menu import _SCRIPT, available


def test_start_menu_action_is_explicit_and_limited_to_windows_build(qapp):
    window = MainWindow(build_registry())
    try:
        assert window.start_menu_action.text() == "Add to Start menu…"
        assert window.desktop_shortcut_action.text() == "Add Desktop shortcut…"
        assert window.start_menu_action in window.file_menu.actions()
        assert window.desktop_shortcut_action in window.file_menu.actions()
        assert window.start_menu_action.isEnabled() == available()
        assert window.desktop_shortcut_action.isEnabled() == available()
    finally:
        window.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcut integration")
@pytest.mark.parametrize("location", ["start_menu", "desktop"])
def test_windows_shortcut_creation_and_no_overwrite(tmp_path, location):
    target = tmp_path / "PDFToolkit.exe"
    target.write_bytes(b"test")
    env = os.environ.copy()
    env["PDF_TOOLKIT_SHORTCUT_TARGET"] = str(target)
    env["PDF_TOOLKIT_SHORTCUT_LOCATION"] = location
    env["PDF_TOOLKIT_TEST_PROGRAMS"] = str(tmp_path)
    script = _SCRIPT.replace(
        "[Environment]::GetFolderPath('Programs')", "$env:PDF_TOOLKIT_TEST_PROGRAMS"
    )
    script = script.replace(
        "[Environment]::GetFolderPath('DesktopDirectory')", "$env:PDF_TOOLKIT_TEST_PROGRAMS"
    )
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    first = subprocess.run(command, env=env, capture_output=True, timeout=30, check=False)
    assert first.returncode == 0, first.stderr.decode(errors="replace")
    shortcut = tmp_path / "PDF Toolkit.lnk"
    before = shortcut.read_bytes()
    assert before
    second = subprocess.run(command, env=env, capture_output=True, timeout=30, check=False)
    assert second.returncode == 2
    assert shortcut.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["PDF Toolkit.lnk", "PDFToolkit.exe"]
