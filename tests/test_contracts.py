import pytest

from local_pdf_toolkit.core.contracts import CancellationToken, Progress
from local_pdf_toolkit.core.errors import ConversionCancelled, ErrorCode


def test_cancellation_is_cooperative_and_tokens_are_independent(test_converter, tmp_path):
    token = CancellationToken()
    other = CancellationToken()
    token.cancel()
    token.cancel()
    assert token.is_cancelled
    assert not other.is_cancelled
    with pytest.raises(ConversionCancelled) as error:
        test_converter.convert(tmp_path / "unused.pdf", tmp_path, {}, lambda _: None, token)
    assert error.value.code == ErrorCode.CANCELLED
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("completed,total", [(-1, None), (1, 0), (0, -1), (3, 2)])
def test_impossible_progress_is_rejected(completed, total):
    with pytest.raises(ValueError):
        Progress(completed, total)


def test_progress_supports_known_and_indeterminate_totals():
    assert Progress(2, 10).total == 10
    assert Progress().total is None
    assert Progress(0, 0).completed == 0


def test_synthetic_pdf_fixture_has_valid_basic_structure(fixture_dir):
    # M0 checks fixture integrity only. M1 adds real parser/rendering assertions.
    data = (fixture_dir / "one_page.pdf").read_bytes()
    assert data.startswith(b"%PDF-1.4")
    assert data.endswith(b"%%EOF\n")
    xref_offset = int(data.split(b"startxref\n")[1].splitlines()[0])
    assert data[xref_offset:].startswith(b"xref\n")
