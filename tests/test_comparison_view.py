import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from local_pdf_toolkit.ui.preview import ComparisonCanvas, ComparisonDialog, PageCanvas


def wait(dialog):
    loop = QEventLoop()
    poll, timeout = QTimer(), QTimer()
    poll.timeout.connect(
        lambda: loop.quit() if not dialog.jobs.running and not dialog._pending else None
    )
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start(20)
    timeout.start(15000)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert not dialog.jobs.running and not dialog._pending


def test_comparison_zoom_is_one_preview_pixel_and_survives_resize(qapp, tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 1000), "white").save(source)
    canvas = ComparisonCanvas()
    canvas.resize(450, 350)
    canvas.show()
    canvas.load(source)
    qapp.processEvents()
    assert canvas.transform().m11() < 1
    canvas.set_zoom(100)
    assert canvas.transform().m11() == 1
    canvas.set_zoom(200)
    canvas.resize(500, 400)
    qapp.processEvents()
    assert canvas.transform().m11() == 2
    canvas.fit_page()
    assert canvas.transform().m11() < 1
    # This subclass must not change how the redaction canvas always fits on resize.
    redaction = PageCanvas()
    redaction.resize(400, 300)
    redaction.show()
    redaction.load(source)
    redaction.resetTransform()
    redaction.resize(500, 400)
    qapp.processEvents()
    assert redaction.transform().m11() < 1
    canvas.close()
    redaction.close()


def test_comparison_controls_and_optional_synchronized_pan(qapp, tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 1200), "white").save(source)
    dialog = ComparisonDialog(source, (source,))
    dialog.show()
    try:
        wait(dialog)
        dialog.actual_button.click()
        assert all(canvas.transform().m11() == 1 for canvas in dialog.canvases)
        dialog.zoom.setValue(200)
        assert all(canvas.transform().m11() == 2 for canvas in dialog.canvases)
        first, second = dialog.canvases
        first.set_normalized_center(QPointF(0.65, 0.6))
        qapp.processEvents()
        assert second.normalized_center().x() == pytest.approx(
            first.normalized_center().x(), abs=0.01
        )
        assert second.normalized_center().y() == pytest.approx(
            first.normalized_center().y(), abs=0.01
        )
        wheel = QWheelEvent(
            QPointF(100, 100),
            QPointF(100, 100),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(first.viewport(), wheel)
        assert first.transform().m11() == second.transform().m11() == 2.5
        dialog.sync.setChecked(False)
        before = second.normalized_center()
        first.set_normalized_center(QPointF(0.4, 0.4))
        qapp.processEvents()
        assert second.normalized_center() == before
        dialog.fit_button.click()
        assert all(canvas._fit and canvas.transform().m11() < 1 for canvas in dialog.canvases)
        dialog._request()
        wait(dialog)
        assert all(canvas._fit for canvas in dialog.canvases)
        assert "rendered preview pixels" in dialog.feedback.text()
    finally:
        dialog.close()
        qapp.processEvents()
