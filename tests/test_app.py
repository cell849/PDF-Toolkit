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
