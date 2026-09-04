"""OCR regression tests against real scanned documents.

``media/documents/**/*.pdf`` holds real scans and is not checked into git
(see ``.gitignore``), so these tests only make sense on a workstation that
has that folder -- never in CI. They are gated behind ``MINGADOCS_TEST_ACTUAL_DOCS``
so a plain ``make test`` skips them entirely; run them with
``make test-with-actual-docs``.

For every PDF: page 1 must decode to the ARN encoded in the PDF's own
basename (``<prefix><body>.pdf``, the filename ``services._pages_to_pdf``
writes), and every following page must decode to the continuation marker
(an all-zero body) -- never "no barcode found" and never a volume-start ARN.

Scanning every page of every document is slow (a few hundred pages, each
tried at several tile crops, upscale factors and binarizers). Each run
records which (doc, page) pairs failed to ``.test_actual_docs_failures.json``
under ``MEDIA_ROOT``; set ``MINGADOCS_TEST_ACTUAL_DOCS_FAILED_ONLY=1``
(``make test-with-actual-docs-failed``) to re-test only those pages while
iterating on a fix, then drop back to a full run to confirm nothing else
regressed.
"""
from __future__ import annotations

import io
import json
import os
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from django.conf import settings
from django.test import SimpleTestCase, tag
from PIL import Image

from arnlabels.arn import Arn

from . import ocr

_FEATURE_ENV = "MINGADOCS_TEST_ACTUAL_DOCS"
_FAILED_ONLY_ENV = "MINGADOCS_TEST_ACTUAL_DOCS_FAILED_ONLY"
_ARN_BODY_LEN = 9
_FAILURES_FILE = Path(settings.MEDIA_ROOT) / ".test_actual_docs_failures.json"


def _iter_pdfs() -> list[Path]:
    return sorted(Path(settings.MEDIA_ROOT).glob("documents/*/*/*.pdf"))


def _load_prior_failures() -> list[tuple[str, int]]:
    try:
        raw = json.loads(_FAILURES_FILE.read_text())
    except (OSError, ValueError):
        return []
    return [tuple(entry) for entry in raw]


def _save_failures(entries: list[tuple[str, int]]) -> None:
    _FAILURES_FILE.write_text(json.dumps(sorted(entries)))


def _page_image(page: pdfium.PdfPage) -> Image.Image:
    """The page's embedded scan, at the resolution it was scanned at.

    Each page is a single full-page raster image (that's how
    ``services._pages_to_pdf`` builds the PDF), so extracting the embedded
    image object is the exact bytes OCR would have seen at scan time --
    unlike ``page.render()``, which re-rasterizes through PDFium and can
    introduce its own resampling artifacts.
    """
    for obj in page.get_objects():
        if obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            return obj.get_bitmap(render=False).to_pil().convert("RGB")
    return page.render(scale=1).to_pil().convert("RGB")


@tag("actual_docs")
@unittest.skipUnless(
    os.environ.get(_FEATURE_ENV),
    f"set {_FEATURE_ENV}=1 (make test-with-actual-docs)",
)
class RealDocumentOcrTests(SimpleTestCase):
    """Every ``media/documents/**/*.pdf`` must OCR cleanly, page by page."""

    pdfs: list[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.pdfs = _iter_pdfs()
        if not cls.pdfs:
            raise unittest.SkipTest(f"no PDFs under {settings.MEDIA_ROOT}/documents")

    def test_every_page_ocrs_to_the_expected_arn(self) -> None:
        failures: list[tuple[str, int]] = []
        for path, pages in self._build_plan().items():
            self._check_document(path, pages, failures)
        _save_failures(failures)

    def _build_plan(self) -> Mapping[Path, Sequence[int]]:
        """Which pages of which PDFs to test this run."""
        if not os.environ.get(_FAILED_ONLY_ENV):
            return {
                path: range(len(pdfium.PdfDocument(str(path))))
                for path in self.pdfs
            }

        prior = _load_prior_failures()
        if not prior:
            self.skipTest(
                f"no prior failures recorded in {_FAILURES_FILE}; "
                "run `make test-with-actual-docs` first"
            )
        by_name = {path.name: path for path in self.pdfs}
        plan: dict[Path, list[int]] = {}
        for doc, page in prior:
            if doc in by_name:
                plan.setdefault(by_name[doc], []).append(page)
        return plan

    def _check_document(
        self, path: Path, pages: Sequence[int], failures: list[tuple[str, int]],
    ) -> None:
        stem = path.stem
        self.assertGreater(
            len(stem), _ARN_BODY_LEN,
            f"{path.name}: basename too short to hold prefix + ARN body",
        )
        prefix, body = stem[:-_ARN_BODY_LEN], stem[-_ARN_BODY_LEN:]
        start_arn = Arn(prefix=prefix, body=body).barcode_value()
        continuation_arn = Arn.continuation(prefix).barcode_value()

        pdf = pdfium.PdfDocument(str(path))
        for index in pages:
            with self.subTest(doc=path.name, page=index):
                buf = io.BytesIO()
                _page_image(pdf[index]).save(buf, format="PNG")
                result = ocr.detect_arn(buf.getvalue(), prefix)
                expected = start_arn if index == 0 else continuation_arn
                if result.arn != expected:
                    failures.append((path.name, index))
                self.assertEqual(
                    result.arn, expected,
                    f"{path.name} page {index}: {result.outcome.value} "
                    f"({result.note or result.candidate_count} candidates)",
                )
