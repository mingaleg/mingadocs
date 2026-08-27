"""Tests for the scan intake workflow.

Jobs are exercised synchronously (``jobs._run_scan`` / ``jobs._run_ocr`` called
directly); the scanner is faked via ``MINGADOCS_FAKE_SCANNER``.
"""
from __future__ import annotations

import io
import os
import tempfile
from unittest import mock

import zxingcpp
from django.test import TestCase, override_settings
from PIL import Image

from arnlabels.models import PrintSettings

from . import jobs, ocr, services
from . import scanner as scanner_mod
from .models import Document, ScanBatch, ScanPage
from .scanner import ScannerError, scan_page


def make_page_png(*arns: str, blank: bool = False) -> bytes:
    """A white A4-ish page with the given ARNs rendered as Code 128 barcodes."""
    canvas = Image.new("L", (1000, 1400), 255)
    if not blank:
        y = 40
        for value in arns:
            bc = zxingcpp.create_barcode(value, zxingcpp.BarcodeFormat.Code128)
            strip = Image.fromarray(zxingcpp.write_barcode_to_image(bc))
            strip = strip.resize((600, 160))
            canvas.paste(strip, (60, y))
            y += 260
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


_TMP = tempfile.mkdtemp(prefix="mingadocs-test-media-")


@override_settings(MEDIA_ROOT=_TMP)
class OcrPipelineTests(TestCase):
    def test_single_barcode(self):
        r = ocr.detect_arn(make_page_png("ARN202600042"), "ARN")
        self.assertEqual(r.arn, "ARN202600042")

    def test_no_barcode(self):
        r = ocr.detect_arn(make_page_png(blank=True), "ARN")
        self.assertIsNone(r.arn)
        self.assertIn("no ARN", r.note)

    def test_two_barcodes_unassigned(self):
        r = ocr.detect_arn(
            make_page_png("ARN202600042", "ARN202600043"), "ARN"
        )
        self.assertIsNone(r.arn)
        self.assertEqual(r.candidate_count, 2)

    def test_other_prefix_ignored(self):
        r = ocr.detect_arn(make_page_png("XYZ202600042"), "ARN")
        self.assertIsNone(r.arn)

    def test_falls_back_to_other_binarizers(self):
        """A Code 128 only the fixed-threshold binarizer sees is still found."""
        import zxingcpp
        real = zxingcpp.read_barcodes

        def picky(img, *a, binarizer=None, **kw):
            if binarizer == zxingcpp.Binarizer.LocalAverage:
                return []
            return real(img, *a, binarizer=binarizer, **kw)

        with mock.patch.object(zxingcpp, "read_barcodes", side_effect=picky):
            r = ocr.detect_arn(make_page_png("ARN202600042"), "ARN")
        self.assertEqual(r.arn, "ARN202600042")


@override_settings(MEDIA_ROOT=_TMP)
class ScannerTests(TestCase):
    def test_fake_scanner_env(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(b"hello-png")
            path = fh.name
        try:
            with mock.patch.dict(os.environ, {"MINGADOCS_FAKE_SCANNER": path}):
                self.assertEqual(scan_page(mock.Mock()), b"hello-png")
        finally:
            os.unlink(path)

    def test_scanner_error_when_missing_binary(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(ScannerError):
                scan_page(mock.Mock(sane_device="", resolution_dpi=300, mode="Color"))

    def test_retries_with_fewer_options_on_failure(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "--mode=Color" in cmd:
                return mock.Mock(returncode=1, stdout=b"",
                                 stderr=b"scanimage: unrecognized option '--mode=Color'")
            return mock.Mock(returncode=0, stdout=b"\x89PNG...", stderr=b"")

        with mock.patch("subprocess.run", side_effect=fake_run):
            out = scan_page(mock.Mock(sane_device="d", resolution_dpi=300, mode="Color"))
        self.assertEqual(out, b"\x89PNG...")
        self.assertEqual(len(calls), 2)
        self.assertIn("--resolution=300", calls[1])
        self.assertNotIn("--mode=Color", calls[1])

    def test_rejects_html_error_page_as_output(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(
                returncode=0, stdout=b"<!DOCTYPE HTML><html>...", stderr=b"")):
            with self.assertRaises(ScannerError):
                scan_page(mock.Mock(sane_device="d", resolution_dpi=0, mode=""))

    def test_no_device_selected_errors(self):
        with mock.patch.object(scanner_mod, "list_devices", return_value=["a", "b"]):
            with self.assertRaises(ScannerError):
                scan_page(mock.Mock(sane_device="", resolution_dpi=300, mode="Color"))


def run_scan_sync(page):
    """Run scan + OCR inline for a page (no background pools)."""
    with mock.patch.object(jobs, "enqueue_ocr"):
        jobs._run_scan(page.id)
    page.refresh_from_db()
    if page.scan_status == ScanPage.SCAN_DONE:
        jobs._run_ocr(page.id)
    page.refresh_from_db()


@override_settings(MEDIA_ROOT=_TMP)
class BatchFlowTests(TestCase):
    def _fake(self, data: bytes):
        fh = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fh.write(data)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return mock.patch.dict(os.environ, {"MINGADOCS_FAKE_SCANNER": fh.name})

    def test_scan_stop_flow(self):
        batch = services.start_batch()
        with self._fake(make_page_png("ARN202600042")), \
                mock.patch.object(jobs, "enqueue_scan"):
            page = services.add_scan_page(batch)
            run_scan_sync(page)
        self.assertEqual(page.scan_status, ScanPage.SCAN_DONE)
        self.assertTrue(page.image)
        self.assertTrue(page.thumbnail)
        self.assertEqual(page.detected_arn, "ARN202600042")

        services.stop_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ScanBatch.REVIEW)

    def test_scan_in_progress_blocks_second(self):
        batch = services.start_batch()
        with mock.patch.object(jobs, "enqueue_scan"):
            services.add_scan_page(batch)
            with self.assertRaises(ValueError):
                services.add_scan_page(batch)

    def test_discard_batch_hard_deletes_pages_and_files(self):
        batch = services.start_batch()
        with self._fake(make_page_png("ARN202600042")), \
                mock.patch.object(jobs, "enqueue_scan"):
            page = services.add_scan_page(batch)
            run_scan_sync(page)
        img_path = page.image.path
        thumb_path = page.thumbnail.path
        self.assertTrue(os.path.exists(img_path))

        services.discard_batch(batch)

        self.assertFalse(ScanBatch.objects.filter(pk=batch.pk).exists())
        self.assertFalse(ScanPage.objects.filter(pk=page.pk).exists())
        self.assertFalse(os.path.exists(img_path))
        self.assertFalse(os.path.exists(thumb_path))

    def test_discard_batch_rejects_finalized(self):
        batch = services.start_batch()
        batch.status = ScanBatch.FINALIZED
        batch.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            services.discard_batch(batch)

    def test_discard_view_redirects_to_list(self):
        batch = services.start_batch()
        resp = self.client.post(f"/scans/{batch.id}/discard/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/scans/")
        self.assertFalse(ScanBatch.objects.filter(pk=batch.pk).exists())


@override_settings(MEDIA_ROOT=_TMP)
class AlertTests(TestCase):
    def _page(self, batch, pos, *, detected="", manual="", cont=False,
              scan=ScanPage.SCAN_DONE):
        return ScanPage.objects.create(
            batch=batch, position=pos, scan_status=scan,
            ocr_status=ScanPage.OCR_DONE, detected_arn=detected,
            manual_arn=manual, manual_continuation=cont,
        )

    def test_unassigned_blocks(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected="")
        codes = {a.code for a in services.compute_alerts(b)}
        self.assertIn("unassigned", codes)
        self.assertFalse(services.finalizable(b))

    def test_duplicate_in_batch(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected="ARN202600001")
        self._page(b, 20, detected="ARN202600001")
        self.assertIn("duplicate_in_batch",
                      {a.code for a in services.compute_alerts(b)})

    def test_conflict_with_existing_document(self):
        b = services.start_batch()
        services.stop_batch(b)
        Document.objects.create(start_arn="ARN202600001", page_count=1,
                                pdf="documents/x.pdf")
        self._page(b, 10, detected="ARN202600001")
        self.assertIn("conflict_existing",
                      {a.code for a in services.compute_alerts(b)})

    def test_orphan_continuation(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, cont=True)
        self.assertIn("orphan_continuation",
                      {a.code for a in services.compute_alerts(b)})

    def test_clean_batch_finalizable(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected="ARN202600001")
        self._page(b, 20, cont=True)
        self.assertEqual(services.compute_alerts(b), [])
        self.assertTrue(services.finalizable(b))


@override_settings(MEDIA_ROOT=_TMP)
class FinalizeTests(TestCase):
    def _page(self, batch, pos, **kw):
        buf = io.BytesIO()
        Image.new("RGB", (200, 280), "white").save(buf, format="PNG")
        from django.core.files.base import ContentFile
        p = ScanPage.objects.create(
            batch=batch, position=pos, scan_status=ScanPage.SCAN_DONE,
            ocr_status=ScanPage.OCR_DONE, **kw,
        )
        p.image.save(f"p{pos}.png", ContentFile(buf.getvalue()), save=True)
        return p

    def test_finalize_groups_documents(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected_arn="ARN202600001")
        self._page(b, 20, manual_continuation=True)
        self._page(b, 30, manual_continuation=True)
        self._page(b, 40, detected_arn="ARN202600002")

        docs = services.finalize_batch(b)
        self.assertEqual(len(docs), 2)
        self.assertEqual(sorted(d.page_count for d in docs), [1, 3])
        b.refresh_from_db()
        self.assertEqual(b.status, ScanBatch.FINALIZED)
        self.assertFalse(b.pages.exists())
        for d in docs:
            self.assertTrue(d.pdf.read().startswith(b"%PDF"))

    def test_blocked_finalize_raises(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected_arn="")
        with self.assertRaises(ValueError):
            services.finalize_batch(b)


@override_settings(MEDIA_ROOT=_TMP)
class ViewTests(TestCase):
    def setUp(self):
        p = mock.patch.object(scanner_mod, "list_devices", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def test_pages_render(self):
        b = services.start_batch()
        self.assertEqual(self.client.get("/scans/").status_code, 200)
        self.assertEqual(self.client.get(f"/scans/{b.id}/").status_code, 200)
        r = self.client.get("/scans/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="labels"')
        self.assertContains(r, 'id="scanner"')

    def test_old_label_settings_url_redirects(self):
        r = self.client.get("/labels/settings/")
        self.assertRedirects(r, "/scans/settings/#labels",
                             fetch_redirect_response=False)

    def test_settings_saves_each_section(self):
        r = self.client.post("/scans/settings/", {
            "section": "scanner", "resolution_dpi": 600, "mode": "Gray",
            "ocr_timeout_seconds": 15, "sane_device": "escl:https://h:443",
        })
        self.assertEqual(r.status_code, 302)
        from .models import ScanSettings
        cfg = ScanSettings.get_solo()
        self.assertEqual(cfg.resolution_dpi, 600)
        self.assertEqual(cfg.sane_device, "escl:https://h:443")

    def test_review_redirects_while_scanning(self):
        b = services.start_batch()
        r = self.client.get(f"/scans/{b.id}/review/")
        self.assertRedirects(r, f"/scans/{b.id}/")

    def test_status_json_shape(self):
        b = services.start_batch()
        data = self.client.get(f"/scans/{b.id}/status/").json()
        self.assertEqual(
            set(data),
            {"status", "scan_in_progress", "pages", "alerts", "finalizable"},
        )

    def test_scan_conflict_when_in_progress(self):
        b = services.start_batch()
        with mock.patch.object(jobs, "enqueue_scan"):
            ScanPage.objects.create(batch=b, position=10)
            r = self.client.post(f"/scans/{b.id}/scan/")
        self.assertEqual(r.status_code, 409)

    def test_finalize_conflict_with_alerts(self):
        b = services.start_batch()
        services.stop_batch(b)
        ScanPage.objects.create(batch=b, position=10,
                                scan_status=ScanPage.SCAN_DONE)
        r = self.client.post(f"/scans/{b.id}/finalize/")
        self.assertEqual(r.status_code, 409)


@override_settings(MEDIA_ROOT=_TMP)
class RecoverStaleTests(TestCase):
    def test_pending_marked_failed(self):
        b = services.start_batch()
        p = ScanPage.objects.create(batch=b, position=10,
                                    scan_status=ScanPage.SCAN_PENDING)
        jobs.recover_stale()
        p.refresh_from_db()
        self.assertEqual(p.scan_status, ScanPage.SCAN_FAILED)
