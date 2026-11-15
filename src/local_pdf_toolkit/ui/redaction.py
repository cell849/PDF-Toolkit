"""Manual redaction control: marks are bound to one unchanged source file."""

import json
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from local_pdf_toolkit.ui.preview import PreviewDialog


def signature(paths):
    if len(paths) != 1:
        return None
    path = Path(paths[0])
    try:
        stat = path.stat()
        return str(path), stat.st_size, stat.st_mtime_ns
    except OSError:
        return None


class RedactionControl(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.bound_source = None
        self.marked = {}
        self.source_digest = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("No areas marked")
        row.addWidget(self.summary, 1)
        button = QPushButton("Mark areas…")
        button.clicked.connect(self.open)
        row.addWidget(button)

    def value(self):
        if self.bound_source is None or signature(self.window._paths) != self.bound_source:
            return "[]"
        regions = [
            {"page": page, "x0": rect[0], "y0": rect[1], "x1": rect[2], "y1": rect[3]}
            for page, rectangles in sorted(self.marked.items())
            for rect in rectangles
        ]
        return json.dumps(regions)

    def digest(self):
        return self.source_digest if self.value() != "[]" else ""

    def open(self):
        current = signature(self.window._paths)
        if current is None:
            self.window.statusBar().showMessage("Add exactly one PDF before marking areas.")
            return
        previous = self.marked if current == self.bound_source else {}
        dialog = PreviewDialog(
            self.window._paths[0],
            self.window,
            marking=True,
            regions=previous,
            source_digest=self.source_digest if previous else "",
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if signature(self.window._paths) != current:
                    self.window.statusBar().showMessage("The source changed. Mark it again.")
                    return
                self.bound_source = current
                self.marked = dialog.marked
                self.source_digest = dialog.source_digest
                count = sum(len(rectangles) for rectangles in self.marked.values())
                self.summary.setText(
                    f"{count} areas on {sum(bool(r) for r in self.marked.values())} pages"
                )
        finally:
            dialog.deleteLater()
