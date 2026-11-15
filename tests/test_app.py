from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow


def test_application_registry_and_all_option_forms(qapp):
    registry = build_registry()
    operations = registry.list_operations()
    assert len(operations) >= 25
    assert registry.get("image.to_pdf").spec.input_mode == "multiple"
    assert registry.get("pdf.merge").spec.input_mode == "multiple"
    assert registry.get("pdf.to_docx")
    assert registry.get("office.to_pdf")
    window = MainWindow(registry)
    try:
        for index, spec in enumerate(operations):
            window.operation_list.setCurrentRow(index)
            assert set(window._editors) == {definition.name for definition in spec.options}
            values = {name: getter() for name, getter in window._editors.items()}
            assert values == {d.name: d.default for d in spec.options}
    finally:
        window.close()


def test_search_cannot_run_hidden_operation(qapp):
    window = MainWindow(build_registry())
    try:
        window.search.setText("Compress PDF")
        selected = window._operations[window.operation_list.currentRow()]
        assert selected.operation_id == "pdf.compress"
        window.search.setText("no matching operation")
        assert window.operation_list.currentRow() == -1
        assert not window.start_button.isEnabled()
        assert not window._editors
        window.search.clear()
        assert window.start_button.isEnabled()
    finally:
        window.close()


def test_library_cards_categories_and_compact_workspace(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea

    window = MainWindow(build_registry())
    window.show()
    try:
        assert window.pages.currentWidget() == window.dashboard
        assert len(window.library.cards) == len(window._operations)
        window.navigation.setCurrentRow(4)  # Optimize
        assert (
            sum(
                not window.operation_list.item(i).isHidden() for i in range(len(window._operations))
            )
            == 1
        )
        index = next(
            i for i, spec in enumerate(window._operations) if spec.operation_id == "pdf.compress"
        )
        QTest.mouseClick(window.library.cards[index], Qt.LeftButton)
        assert window.pages.currentWidget() == window.workspace
        assert window.tool_title.text() == "Compress PDF"
        window.resize(760, 620)
        QTest.qWait(80)
        previous_bottom = -1
        for row in range(window.form.rowCount()):
            label = window.form.itemAt(row, window.form.ItemRole.LabelRole).widget()
            field = window.form.itemAt(row, window.form.ItemRole.FieldRole).widget()
            assert label.geometry().top() > previous_bottom
            assert field.geometry().top() > label.geometry().bottom()
            previous_bottom = field.geometry().bottom()
        for scroll in window.workspace.findChildren(QScrollArea):
            assert scroll.horizontalScrollBar().maximum() == 0
        window._set_active(True)
        window._show_library()
        assert window.pages.currentWidget() == window.workspace
        window._set_active(False)
        window._show_library()
        assert window.pages.currentWidget() == window.dashboard
    finally:
        window.close()
