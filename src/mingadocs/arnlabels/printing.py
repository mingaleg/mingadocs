"""Send print jobs to CUPS via pycups."""
from __future__ import annotations

import os
import tempfile

import cups

PrinterAttrs = dict[str, str | int | bool | list[str]]


def list_printers() -> dict[str, PrinterAttrs]:
    """Return ``{queue_name: attributes}`` for all CUPS queues (for settings UI)."""
    return cups.Connection().getPrinters()


def submit_pdf(
    printer: str,
    pdf_bytes: bytes,
    job_name: str = "ARN labels",
    media: str = "A4",
) -> int:
    """Submit a PDF to a CUPS queue. Returns the CUPS job id.

    ``media`` is forced explicitly (default ``A4``): the label grid only lines
    up if the printer uses the same page size the PDF was laid out for. A queue
    defaulting to Letter clips ~18 mm off the bottom - the last label row.
    Scaling is disabled so the grid keeps its absolute positions.
    """
    conn = cups.Connection()
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="arnlabels-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        options = {
            "media": media,
            "fit-to-page": "false",
            "scaling": "100",
        }
        return conn.printFile(printer, path, job_name, options)
    finally:
        os.unlink(path)
