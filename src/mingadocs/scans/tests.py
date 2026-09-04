"""Tests for the scan intake workflow.

Jobs are exercised synchronously (``jobs._run_scan`` / ``jobs._run_ocr`` called
directly); the scanner is faked via ``MINGADOCS_FAKE_SCANNER``.
"""
# Test code legitimately reaches into private job helpers and keeps temp files
# open past the enclosing block.
# pylint: disable=protected-access,consider-using-with
from __future__ import annotations

import io
import os
import tempfile
from unittest import mock

import zxingcpp
from django.test import TestCase, override_settings
from PIL import Image

from . import jobs, ocr, scanner as scanner_mod, services
from .enums import BatchStatus, OcrStatus, ScanStatus
from .models import Document, ScanBatch, ScanPage
from .scanner import ScannerError, scan_page


def make_page_png(*arns: str, blank: bool = False) -> bytes:
    """A white A4-ish page with the given ARNs rendered as Code 128 barcodes."""
    canvas = Image.new("L", (1000, 1400), 255)
    if not blank:
        y = 40
        for value in arns:
            bc = zxingcpp.create_barcode(value, zxingcpp.BarcodeFormat.Code128)
            # zxingcpp.Image exposes __array_interface__ but its stub does not
            # satisfy Pillow's SupportsArrayInterface protocol.
            img_arr = zxingcpp.write_barcode_to_image(bc)
            strip = Image.fromarray(img_arr)  # type: ignore[arg-type]
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
        real = zxingcpp.read_barcodes

        def picky(img, *, binarizer=None, **kw):
            if binarizer == zxingcpp.Binarizer.LocalAverage:
                return []
            return real(img, binarizer=binarizer, **kw)

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
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()), \
                self.assertRaises(ScannerError):
            scan_page(mock.Mock(sane_device="", resolution_dpi=300, mode="Color"))

    def test_retries_with_fewer_options_on_failure(self):
        calls = []

        def fake_run(cmd, **_kw):
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
                returncode=0, stdout=b"<!DOCTYPE HTML><html>...", stderr=b"")), \
                self.assertRaises(ScannerError):
            scan_page(mock.Mock(sane_device="d", resolution_dpi=0, mode=""))

    def test_no_device_selected_errors(self):
        with mock.patch.object(
            scanner_mod, "list_devices", return_value=["a", "b"]
        ), self.assertRaises(ScannerError):
            scan_page(mock.Mock(sane_device="", resolution_dpi=300, mode="Color"))


def run_scan_sync(page):
    """Run scan + OCR inline for a page (no background pools)."""
    with mock.patch.object(jobs, "enqueue_ocr"):
        jobs._run_scan(page.id)
    page.refresh_from_db()
    if page.scan_status == ScanStatus.DONE:
        jobs._run_ocr(page.id)
    page.refresh_from_db()


@override_settings(MEDIA_ROOT=_TMP)
class BatchFlowTests(TestCase):
    def _fake(self, data: bytes):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(data)
        self.addCleanup(os.unlink, fh.name)
        return mock.patch.dict(os.environ, {"MINGADOCS_FAKE_SCANNER": fh.name})

    def test_scan_stop_flow(self):
        batch = services.start_batch()
        with self._fake(make_page_png("ARN202600042")), \
                mock.patch.object(jobs, "enqueue_scan"):
            page = services.add_scan_page(batch)
            run_scan_sync(page)
        self.assertEqual(page.scan_status, ScanStatus.DONE)
        self.assertTrue(page.image)
        self.assertTrue(page.thumbnail)
        self.assertEqual(page.detected_arn, "ARN202600042")

        services.stop_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.REVIEW)

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
        batch.status = BatchStatus.FINALIZED
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
              scan=ScanStatus.DONE):
        return ScanPage.objects.create(
            batch=batch, position=pos, scan_status=scan,
            ocr_status=OcrStatus.DONE, detected_arn=detected,
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
    def _page(self, batch, pos, *, with_thumb=True, **kw):
        buf = io.BytesIO()
        Image.new("RGB", (200, 280), "white").save(buf, format="PNG")
        from django.core.files.base import ContentFile
        p = ScanPage.objects.create(
            batch=batch, position=pos, scan_status=ScanStatus.DONE,
            ocr_status=OcrStatus.DONE, **kw,
        )
        p.image.save(f"p{pos}.png", ContentFile(buf.getvalue()), save=False)
        if with_thumb:
            thumb_buf = io.BytesIO()
            Image.new("RGB", (50, 70), "white").save(thumb_buf, format="JPEG")
            p.thumbnail.save(
                f"p{pos}-thumb.jpg", ContentFile(thumb_buf.getvalue()), save=False,
            )
        p.save()
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
        self.assertEqual(b.status, BatchStatus.FINALIZED)
        self.assertFalse(b.pages.exists())
        for d in docs:
            self.assertTrue(d.pdf.read().startswith(b"%PDF"))

    def test_blocked_finalize_raises(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected_arn="")
        with self.assertRaises(ValueError):
            services.finalize_batch(b)

    def test_finalize_copies_first_page_thumbnail(self):
        b = services.start_batch()
        services.stop_batch(b)
        first = self._page(b, 10, detected_arn="ARN202600001")
        self._page(b, 20, manual_continuation=True)
        expected = first.thumbnail.read()

        docs = services.finalize_batch(b)
        self.assertEqual(len(docs), 1)
        self.assertTrue(docs[0].thumbnail)
        self.assertEqual(docs[0].thumbnail.read(), expected)

    def test_finalize_without_a_first_page_thumbnail_leaves_it_blank(self):
        b = services.start_batch()
        services.stop_batch(b)
        self._page(b, 10, detected_arn="ARN202600001", with_thumb=False)

        docs = services.finalize_batch(b)
        self.assertFalse(docs[0].thumbnail)


@override_settings(MEDIA_ROOT=_TMP)
class ThumbnailRegenTests(TestCase):
    """`jobs.enqueue_thumbnail_regen` and the settings-page endpoints."""

    def setUp(self):
        # Module-level job state outlives any one test's DB transaction.
        self.addCleanup(self._reset_thumb_state)

    def _reset_thumb_state(self):
        with jobs._thumb_lock:
            jobs._thumb_state.running = False
            jobs._thumb_state.processed = 0
            jobs._thumb_state.failed = 0
            jobs._thumb_state.total = 0

    def _finalized_doc(self, *, with_thumb=True):
        b = services.start_batch()
        services.stop_batch(b)
        buf = io.BytesIO()
        Image.new("RGB", (200, 280), "white").save(buf, format="PNG")
        from django.core.files.base import ContentFile
        p = ScanPage.objects.create(
            batch=b, position=10, scan_status=ScanStatus.DONE,
            ocr_status=OcrStatus.DONE, detected_arn=f"ARN2026{b.id:05d}",
        )
        p.image.save("p.png", ContentFile(buf.getvalue()), save=False)
        if with_thumb:
            thumb_buf = io.BytesIO()
            Image.new("RGB", (50, 70), "white").save(thumb_buf, format="JPEG")
            p.thumbnail.save(
                "p-thumb.jpg", ContentFile(thumb_buf.getvalue()), save=False,
            )
        p.save()
        return services.finalize_batch(b)[0]

    def test_regenerate_one_thumbnail_builds_a_real_jpeg(self):
        doc = self._finalized_doc(with_thumb=False)
        self.assertFalse(doc.thumbnail)

        self.assertTrue(jobs._regenerate_one_thumbnail(doc.id))

        doc.refresh_from_db()
        self.assertTrue(doc.thumbnail)
        self.assertTrue(doc.thumbnail.read().startswith(b"\xff\xd8"))

    def test_regenerate_one_thumbnail_without_a_pdf_fails_gracefully(self):
        doc = Document.objects.create(start_arn="ARN202699999", page_count=1)
        self.assertFalse(jobs._regenerate_one_thumbnail(doc.id))

    def test_run_thumbnail_regen_only_missing_skips_existing(self):
        already_has = self._finalized_doc(with_thumb=True)
        was_missing = self._finalized_doc(with_thumb=False)
        original = already_has.thumbnail.read()

        jobs._run_thumbnail_regen(only_missing=True)

        status = jobs.thumbnail_regen_status()
        self.assertEqual(
            (status.running, status.total, status.processed, status.failed),
            (False, 1, 1, 0),
        )
        already_has.refresh_from_db()
        was_missing.refresh_from_db()
        self.assertEqual(already_has.thumbnail.read(), original)
        self.assertTrue(was_missing.thumbnail)

    def test_enqueue_thumbnail_regen_rejects_concurrent_runs(self):
        with mock.patch.object(jobs._THUMB_POOL, "submit"):
            self.assertTrue(jobs.enqueue_thumbnail_regen(only_missing=True))
            self.assertFalse(jobs.enqueue_thumbnail_regen(only_missing=True))

    def test_regenerate_view_starts_a_pass(self):
        with mock.patch.object(
            jobs, "enqueue_thumbnail_regen", return_value=True
        ) as enqueue:
            r = self.client.post(
                "/scans/documents/thumbnails/regenerate/", {"scope": "all"}
            )
        enqueue.assert_called_once_with(only_missing=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/settings/#documents")

    def test_regenerate_view_reports_already_running(self):
        with mock.patch.object(jobs, "enqueue_thumbnail_regen", return_value=False):
            r = self.client.post(
                "/scans/documents/thumbnails/regenerate/", {"scope": "missing"}
            )
        self.assertEqual(r.status_code, 302)

    def test_regenerate_status_endpoint_shape(self):
        r = self.client.get("/scans/documents/thumbnails/regenerate/status/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            set(r.json()), {"running", "processed", "failed", "total"}
        )


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

    def test_settings_moved_to_own_module(self):
        self.assertRedirects(self.client.get("/scans/settings/"), "/settings/",
                             fetch_redirect_response=False)

    def test_document_list_page(self):
        b = services.start_batch()
        services.stop_batch(b)
        Document.objects.create(start_arn="ARN202600042", page_count=3, batch=b)
        r = self.client.get("/scans/documents/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ARN 2026 00 042")

    def test_document_list_thumbnail_view_paginates_5x10(self):
        from django.core.files.base import ContentFile

        for i in range(120):
            doc = Document.objects.create(
                start_arn=f"ARN{i:09d}", page_count=1,
            )
            buf = io.BytesIO()
            Image.new("RGB", (50, 70), "white").save(buf, format="JPEG")
            doc.thumbnail.save(
                f"{doc.start_arn}-thumb.jpg", ContentFile(buf.getvalue()), save=True,
            )

        r = self.client.get("/scans/documents/?view=thumbnails")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 3)
        self.assertEqual(len(r.context["page_obj"]), 50)

    def test_document_thumb_urls_endpoint(self):
        from django.core.files.base import ContentFile

        for i in range(3):
            doc = Document.objects.create(
                start_arn=f"ARN{i:09d}", page_count=1,
            )
            buf = io.BytesIO()
            Image.new("RGB", (50, 70), "white").save(buf, format="JPEG")
            doc.thumbnail.save(
                f"{doc.start_arn}-thumb.jpg", ContentFile(buf.getvalue()), save=True,
            )

        r = self.client.get("/scans/documents/thumbnails/1/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["urls"]), 3)

        r = self.client.get("/scans/documents/thumbnails/2/")
        self.assertEqual(r.json()["urls"], [])

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
        self.assertEqual(data["status"], BatchStatus.SCANNING.value)

    def test_reorder_rejects_malformed_body(self):
        b = services.start_batch()
        services.stop_batch(b)
        r = self.client.post(
            f"/scans/{b.id}/reorder/", data="{\"ids\": [\"nope\"]}",
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_scan_conflict_when_in_progress(self):
        b = services.start_batch()
        with mock.patch.object(jobs, "enqueue_scan"):
            ScanPage.objects.create(batch=b, position=10)
            r = self.client.post(f"/scans/{b.id}/scan/")
        self.assertEqual(r.status_code, 409)

    def test_continuation_pages_labelled_page_n(self):
        b = services.start_batch()
        services.stop_batch(b)
        ScanPage.objects.create(batch=b, position=10,
                                scan_status=ScanStatus.DONE,
                                ocr_status=OcrStatus.DONE,
                                detected_arn="ARN202600001")
        for pos in (20, 30):
            ScanPage.objects.create(batch=b, position=pos,
                                    scan_status=ScanStatus.DONE,
                                    ocr_status=OcrStatus.DONE,
                                    manual_continuation=True)
        pages = self.client.get(f"/scans/{b.id}/status/").json()["pages"]
        self.assertEqual([p["arn_label"] for p in pages],
                         ["ARN 2026 00 001", "page 2", "page 3"])

    def test_page_arn_override_takes_split_year_volume_index(self):
        b = services.start_batch()
        services.stop_batch(b)
        p = ScanPage.objects.create(batch=b, position=10,
                                    scan_status=ScanStatus.DONE,
                                    ocr_status=OcrStatus.DONE)
        r = self.client.post(f"/scans/{b.id}/pages/{p.id}/arn/", {
            "mode": "arn", "arn_prefix": "ARN",
            "arn_year": "2026", "arn_volume": "0", "arn_index": "42",
        })
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.manual_arn, "ARN202600042")

    def test_page_detail_prefills_volume_from_batch_majority(self):
        b = services.start_batch()
        services.stop_batch(b)
        for pos, arn in ((10, "ARN202607001"), (20, "ARN202607002")):
            ScanPage.objects.create(batch=b, position=pos,
                                    scan_status=ScanStatus.DONE,
                                    ocr_status=OcrStatus.DONE,
                                    detected_arn=arn)
        p = ScanPage.objects.create(batch=b, position=30,
                                    scan_status=ScanStatus.DONE)
        r = self.client.get(f"/scans/{b.id}/pages/{p.id}/")
        self.assertEqual(r.context["manual_volume"], "07")

    def test_page_arn_override_rejects_bad_index(self):
        b = services.start_batch()
        services.stop_batch(b)
        p = ScanPage.objects.create(batch=b, position=10,
                                    scan_status=ScanStatus.DONE)
        r = self.client.post(f"/scans/{b.id}/pages/{p.id}/arn/", {
            "mode": "arn", "arn_prefix": "ARN",
            "arn_year": "2026", "arn_volume": "0", "arn_index": "9999",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("arn_index", r.json()["errors"])

    def test_finalize_conflict_with_alerts(self):
        b = services.start_batch()
        services.stop_batch(b)
        ScanPage.objects.create(batch=b, position=10,
                                scan_status=ScanStatus.DONE)
        r = self.client.post(f"/scans/{b.id}/finalize/")
        self.assertEqual(r.status_code, 409)


@override_settings(MEDIA_ROOT=_TMP)
class RecoverStaleTests(TestCase):
    def test_pending_marked_failed(self):
        b = services.start_batch()
        p = ScanPage.objects.create(batch=b, position=10,
                                    scan_status=ScanStatus.PENDING)
        jobs.recover_stale()
        p.refresh_from_db()
        self.assertEqual(p.scan_status, ScanStatus.FAILED)
