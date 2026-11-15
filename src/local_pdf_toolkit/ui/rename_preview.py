"""Live filename plan; planning never writes or renames an input."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.core.errors import ConversionError


class RenamePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan_key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("New names")
        title.setObjectName("section")
        layout.addWidget(title)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Original", "New copy"))
        self.table.setAccessibleName("Original filenames and planned copy names")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setShowGrid(False)
        layout.addWidget(self.table, 1)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("muted")
        layout.addWidget(self.notice)

    def update_plan(self, paths, options):
        from local_pdf_toolkit.converters.rename_copies import plan_names

        key = (tuple(paths), tuple(sorted(options.items())))
        if key == self._plan_key:
            return
        self._plan_key = key
        try:
            names = plan_names(tuple(paths), options) if paths else ()
        except (ConversionError, ValueError) as error:
            self.table.setRowCount(0)
            self.notice.setText(str(error))
            return
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(paths))
            for row, (source, name) in enumerate(zip(paths, names, strict=True)):
                for column, value in enumerate((source.name, name)):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.table.setItem(row, column, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.notice.setText(
            "Separate copies in the chosen folder. Originals and file contents stay unchanged."
            if paths
            else "Add files to preview their new names."
        )
