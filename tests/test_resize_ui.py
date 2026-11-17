from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.controls import SliderNumber, TargetSizeEditor
from local_pdf_toolkit.ui.main_window import MainWindow
from local_pdf_toolkit.ui.preview import ComparisonDialog


def select(window, operation):
    window.operation_list.setCurrentRow(
        next(i for i, spec in enumerate(window._operations) if spec.operation_id == operation)
    )


def test_dpi_accepts_precise_typing_and_only_slider_snaps(qapp):
    window = MainWindow(build_registry())
    try:
        select(window, "pdf.to_jpeg")
        control = next(item for item in window.findChildren(SliderNumber) if item.landmarks)
        control.number.setFocus()
        control.number.selectAll()
        QTest.keyClicks(control.number, "276")
        QTest.keyClick(control.number, Qt.Key.Key_Return)
        assert window._editors["dpi"]() == 276
        assert control.slider.value() == 276
        control.slider.setSliderDown(True)
        control.slider.setValue(298)
        control.slider.setSliderDown(False)
        assert window._editors["dpi"]() == 300
        assert "300 DPI" in window.summary.text()
        control.slider.setFocus()
        QTest.keyClick(control.slider, Qt.Key.Key_Right)
        assert window._editors["dpi"]() == 301
        assert "301 DPI" in window.summary.text()
        control.number.selectAll()
        QTest.keyClicks(control.number, "298")
        QTest.keyClick(control.number, Qt.Key.Key_Return)
        assert window._editors["dpi"]() == 298
        assert control.slider.value() == 298
        assert control.number.minimum() == 10
        assert control.number.maximum() == 1200
    finally:
        window.close()


def test_paired_target_size_accepts_fractional_units_and_explains_percent(qapp):
    window = MainWindow(build_registry())
    try:
        select(window, "image.to_jpeg")
        target = window.findChild(TargetSizeEditor)
        assert target is not None
        target.unit.setCurrentIndex(target.unit.findData("MB"))
        target.amount.setValue(1.25)
        assert window._editors["target_value"]() == 1.25
        assert window._editors["target_unit"]() == "MB"
        assert window._editors["target_kib"]() == 0
        assert not any(
            "KiB, 0" in window.form.itemAt(row, window.form.ItemRole.LabelRole).widget().text()
            for row in range(window.form.rowCount())
            if window.form.itemAt(row, window.form.ItemRole.LabelRole) is not None
        )
        target.unit.setCurrentIndex(target.unit.findData("percent"))
        target.amount.setValue(25)
        assert window._editors["target_unit"]() == "percent"
        assert "Keep this percentage" in target.hint.text()
        assert "% of original" == target.unit.currentText()
        assert target.amount.maximum() == 100
        assert not window._editors["allow_downscale"]()
        assert window._editors["resize_percent"]() == 100
    finally:
        window.close()


def test_comparison_uses_selected_source_and_excludes_json_reports(qapp, tmp_path):
    window = MainWindow(build_registry())
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    output = tmp_path / "b.jpg"
    Image.new("RGB", (10, 10), "red").save(a)
    Image.new("RGB", (10, 10), "blue").save(b)
    try:
        window.add_paths((a, b))
        window._results = {0: (tmp_path / "a.report.json",), 1: (output, tmp_path / "b.json")}
        window.files.setCurrentRow(0)
        assert window._comparison_paths() == (a, ())
        assert not window.compare_button.isEnabled()
        window.files.setCurrentRow(1)
        assert window._comparison_paths() == (b, (output,))
        assert window.compare_button.isEnabled()
        window._set_active(True)
        assert not window.compare_button.isEnabled()
        window._set_active(False)
        assert window.compare_button.isEnabled()
        window._clear()
        assert not window.compare_button.isEnabled()
    finally:
        window.close()


def wait_for_comparison(dialog):
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(
        lambda: loop.quit() if not dialog.jobs.running and not dialog._pending else None
    )
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start(20)
    timeout.start(15000)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert not dialog.jobs.running and not dialog._pending


def test_comparison_worker_shows_native_dimensions_bytes_and_cleans_up(qapp, tmp_path):
    source, output = tmp_path / "source.png", tmp_path / "output.jpg"
    Image.new("RGB", (2200, 1600), "red").save(source)
    Image.new("RGB", (1100, 800), "blue").save(output)
    dialog = ComparisonDialog(source, (output,))
    temporary = Path(dialog._temp.name)
    try:
        wait_for_comparison(dialog)
        assert "2200 × 1600 px" in dialog.details[0].text()
        assert "1100 × 800 px" in dialog.details[1].text()
        assert f"{source.stat().st_size:,} bytes" in dialog.details[0].text()
        assert f"{output.stat().st_size:,} bytes" in dialog.details[1].text()
        assert all(not canvas._image_rect.isEmpty() for canvas in dialog.canvases)
        assert max(dialog.canvases[0]._image_rect.size().toTuple()) <= 1400
    finally:
        dialog.close()
        qapp.processEvents()
    assert not temporary.exists()


def test_closing_comparison_cancels_worker_before_removing_temporary_files(qapp, tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (200, 100), "white").save(source)
    dialog = ComparisonDialog(source, (source,))
    temporary = Path(dialog._temp.name)
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    dialog.jobs.finished.connect(loop.quit)
    dialog.close()
    assert dialog._closing
    timeout.start(15000)
    loop.exec()
    timeout.stop()
    assert not dialog.jobs.running
    assert not temporary.exists()
