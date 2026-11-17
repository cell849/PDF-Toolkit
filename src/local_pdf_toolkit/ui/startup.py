"""A small, nonblocking visual indication while the desktop window starts."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QVBoxLayout

from local_pdf_toolkit.ui.design import DARK, LIGHT
from local_pdf_toolkit.ui.icons import app_icon


class StartupScreen(QFrame):
    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("startup")
        self.setAccessibleName("Local PDF Toolkit is starting")
        colors = DARK if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT
        self.setStyleSheet(f"""
            QFrame#startup {{ background: {colors["surface"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]}; border-radius: 12px; }}
            QLabel {{ background: transparent; border: 0; color: {colors["text"]}; }}
            QLabel#startupStatus {{ color: {colors["secondary"]}; }}
            QProgressBar {{ background: {colors["sidebar"]}; border: 0; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {colors["accent"]}; border-radius: 2px; }}
        """)
        self.resize(360, 205)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(48, 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        title = QLabel("Local PDF Toolkit")
        font = title.font()
        font.setPointSizeF(max(font.pointSizeF(), 10) + 3)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        status = QLabel("Starting…")
        status.setObjectName("startupStatus")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status)
        progress = QProgressBar()
        progress.setAccessibleName("Starting Local PDF Toolkit")
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(4)
        layout.addWidget(progress)
        if screen := QApplication.primaryScreen():
            self.move(screen.availableGeometry().center() - self.rect().center())
