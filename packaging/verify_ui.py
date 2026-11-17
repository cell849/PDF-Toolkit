"""Run real Qt workflow regressions and retain synthetic rendered evidence."""

import os
from pathlib import Path

import pytest


class Evidence:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.when != "call":
            return
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        folder = Path("ui-evidence")
        folder.mkdir(exist_ok=True)
        for index, window in enumerate(app.topLevelWidgets()):
            if window.isVisible() and hasattr(window, "_operations"):
                app.processEvents()
                name = "".join(c if c.isalnum() or c in "-_" else "_" for c in item.name)
                window.grab().save(str(folder / f"{name}-{index}.png"))


if __name__ == "__main__":
    print(f"Qt platform: {os.environ.get('QT_QPA_PLATFORM', 'default')}", flush=True)
    raise SystemExit(
        pytest.main(
            [
                "tests/test_workspace.py",
                "tests/test_workspace_races.py",
                "tests/test_file_tools_ui.py",
                "tests/test_document_preview.py",
                "tests/test_ux_shell.py",
                "tests/test_control_polish.py",
                "tests/test_inspector_layout.py",
                "-q",
                "--timeout=60",
            ],
            plugins=[Evidence()],
        )
    )
