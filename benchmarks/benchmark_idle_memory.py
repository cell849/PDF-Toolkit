"""Measure a freshly opened idle window on Linux; run in a fresh process."""

import json
import time
from pathlib import Path

started = time.perf_counter()

from PySide6.QtWidgets import QApplication  # noqa: E402

from local_pdf_toolkit.app import build_registry  # noqa: E402
from local_pdf_toolkit.ui.main_window import MainWindow  # noqa: E402

app = QApplication([])
window = MainWindow(build_registry())
window.show()
for _ in range(30):
    app.processEvents()
elapsed = time.perf_counter() - started
fields = {}
for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
    key, _, value = line.partition(":")
    if key in {"Rss", "Pss", "Private_Clean", "Private_Dirty"}:
        fields[key] = int(value.split()[0])
print(
    json.dumps(
        {
            "startup_seconds": round(elapsed, 4),
            "rss_kib": fields["Rss"],
            "pss_kib": fields["Pss"],
            "private_kib": fields["Private_Clean"] + fields["Private_Dirty"],
        },
        sort_keys=True,
    )
)
window.close()
