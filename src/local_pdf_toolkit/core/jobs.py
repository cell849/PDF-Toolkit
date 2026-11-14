"""One spawned process at a time; Qt polls messages without blocking its event loop."""

import multiprocessing

from PySide6.QtCore import QObject, QTimer, Signal

from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError


def _convert(converter, input_path, output_dir, options, sender, cancellation):
    try:
        paths = converter.convert(
            input_path,
            output_dir,
            options,
            lambda value: sender.send(("progress", value)),
            CancellationToken(cancellation),
        )
        sender.send(("result", paths))
    except ConversionError as exc:
        sender.send(("error", (exc.code.value, str(exc))))
    except Exception:
        sender.send(("error", ("conversion_failed", "Unexpected converter failure.")))
    finally:
        sender.close()


class JobController(QObject):
    progress = Signal(object)
    finished = Signal(object, object)  # paths, (code, message) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._context = multiprocessing.get_context("spawn")
        self._process = None
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self):
        return self._process is not None

    def start(self, converter, input_path, output_dir, options):
        if self.running:
            raise RuntimeError("A conversion is already running.")
        self._receiver, sender = self._context.Pipe(duplex=False)
        self._cancellation = self._context.Event()
        self._result = None
        self._error = None
        process = self._context.Process(
            target=_convert,
            args=(converter, input_path, output_dir, options, sender, self._cancellation),
        )
        try:
            process.start()
        except Exception:
            self._receiver.close()
            sender.close()
            raise
        sender.close()
        self._process = process
        self._timer.start()

    def cancel(self):
        if self.running:
            self._cancellation.set()

    def _drain(self):
        try:
            while self._receiver.poll():
                kind, value = self._receiver.recv()
                if kind == "progress":
                    self.progress.emit(value)
                elif kind == "result":
                    self._result = value
                else:
                    self._error = value
        except EOFError:
            pass

    def _poll(self):
        self._drain()
        if self._process.is_alive():
            return
        self._process.join()
        # A final message may arrive between the first drain and process exit.
        self._drain()
        self._process.close()
        self._process = None
        self._receiver.close()
        self._timer.stop()
        if self._result is None and self._error is None:
            self._error = ("conversion_failed", "Conversion process stopped unexpectedly.")
        self.finished.emit(self._result or (), self._error)
