from django.test import TestCase

from .arn import Arn, continuation_page_arns, volume_page_arns
from .enums import PageType
from .label_templates import AVERY_L4731REV as T
from .models import VolumeAllocation
from .pdf import render_sheet
from . import services
from .services import LabelBatchInput


class ArnTests(TestCase):
    def test_volume_start_format(self):
        a = Arn.volume_start("ARN", 2026, 4, 42)
        self.assertEqual(a.body, "202604042")
        self.assertEqual(a.barcode_value(), "ARN202604042")
        self.assertEqual(a.human_readable(), "ARN 2026 04 042")
        self.assertFalse(a.is_continuation)

    def test_continuation(self):
        a = Arn.continuation("X")
        self.assertEqual(a.body, "000000000")
        self.assertTrue(a.is_continuation)
        self.assertEqual(a.human_readable(), "X 000000000")

    def test_parts_decode(self):
        parts = Arn("ARN", "202604042").parts
        assert parts is not None
        self.assertEqual((parts.year, parts.volume, parts.index), (2026, 4, 42))
        self.assertIsNone(Arn.continuation("ARN").parts)

    def test_rejects_bad_body(self):
        with self.assertRaises(ValueError):
            Arn("ARN", "12345")
        with self.assertRaises(ValueError):
            Arn("", "202604042")

    def test_volume_page_arns_inclusive(self):
        arns = volume_page_arns("ARN", 2026, 0, 5)
        self.assertEqual(len(arns), 6)
        self.assertEqual(arns[-1].body, "202600005")

    def test_continuation_page_all_same(self):
        arns = continuation_page_arns("ARN", 10)
        self.assertEqual(len(arns), 10)
        self.assertTrue(all(x.is_continuation for x in arns))

    def test_invalid_index(self):
        with self.assertRaises(ValueError):
            Arn.volume_start("ARN", 2026, 0, 1000)


class ArnParseTests(TestCase):
    def test_parse_ok(self):
        a = Arn.parse("ARN202600042", "ARN")
        self.assertEqual(a.body, "202600042")
        self.assertFalse(a.is_continuation)

    def test_parse_strips_whitespace(self):
        self.assertEqual(Arn.parse("  ARN000000000\n", "ARN").body, "000000000")

    def test_parse_wrong_prefix(self):
        with self.assertRaises(ValueError):
            Arn.parse("XYZ202600042", "ARN")

    def test_parse_bad_body(self):
        with self.assertRaises(ValueError):
            Arn.parse("ARN20260004", "ARN")
        with self.assertRaises(ValueError):
            Arn.parse("ARN20260004X", "ARN")


class TemplateGeometryTests(TestCase):
    def test_capacity(self):
        self.assertEqual(T.labels_per_sheet, 189)

    def test_first_and_last_origin_inside_page(self):
        x0, y0 = T.label_origin(0, 0)
        self.assertAlmostEqual(x0, 8.4667 - T.offset_x)
        self.assertAlmostEqual(y0, 297 - 13.4938 - 10 + T.offset_y, places=3)
        xl, yl = T.label_origin(T.columns - 1, T.rows - 1)
        self.assertGreaterEqual(yl, 0)
        self.assertLessEqual(xl + T.label_width, T.page_width)
        # right/bottom margins come out symmetric with the left/top ones
        self.assertAlmostEqual(T.page_width - (xl + T.label_width), 8.49, places=1)

    def test_safe_box_inside_label(self):
        lx, ly = T.label_origin(3, 4)
        sx, sy, sw, _sh = T.safe_box(3, 4)
        self.assertGreater(sx, lx)
        self.assertGreater(sy, ly)
        self.assertLess(sw, T.label_width)
        self.assertLessEqual(sx + sw, lx + T.label_width + 1e-9)

    def test_positions_count(self):
        self.assertEqual(len(list(T.positions())), 189)


class PdfTests(TestCase):
    def test_render_volume_sheet(self):
        arns = volume_page_arns("ARN", 2026, 1, 188)
        pdf = render_sheet(T, arns)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_overflow_rejected(self):
        with self.assertRaises(ValueError):
            render_sheet(T, volume_page_arns("ARN", 2026, 1, 200))


class ViewTests(TestCase):
    def test_index_ok(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "arnlabels/index.html")

    def test_index_shows_scan_and_document_islands(self):
        from scans.models import Document

        Document.objects.create(start_arn="ARN202600042", page_count=3)
        r = self.client.get("/")
        self.assertContains(r, "Scan intake")
        self.assertContains(r, "Recent documents")
        # ARN groups are separated in every rendering.
        self.assertContains(r, "ARN 2026 00 042")
        # The redundant tile shortcuts (all present in the top nav) are gone.
        self.assertNotContains(r, 'class="tile"')

    def test_index_configuration_card_covers_printer_and_scanner(self):
        r = self.client.get("/")
        self.assertContains(r, "Printer")
        self.assertContains(r, "Scanner")
        self.assertContains(r, "OCR timeout")
        self.assertContains(r, 'href="/settings/"')  # Edit button

    def test_pages_ok(self):
        self.assertEqual(self.client.get("/labels/").status_code, 200)

    def test_label_settings_url_redirects_to_unified_page(self):
        r = self.client.get("/labels/settings/")
        self.assertRedirects(r, "/settings/#labels",
                             fetch_redirect_response=False)

    def test_download_pdf(self):
        r = self.client.post(
            "/labels/",
            {"page_type": "continuation", "output": "pdf"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn("inline", r["Content-Disposition"])
        self.assertIn("arn-continuation.pdf", r["Content-Disposition"])


class ServiceTests(TestCase):
    def test_suggest_defaults_first_volume(self):
        d = services.suggest_volume_defaults()
        self.assertEqual(d.volume, 0)

    def test_suggest_defaults_increments(self):
        year = services.suggest_volume_defaults().year
        VolumeAllocation.objects.create(year=year, volume=3, max_index=188)
        self.assertEqual(services.suggest_volume_defaults().volume, 4)

    def test_build_volume_sheet_fills_whole_sheet(self):
        sheet = services.build_sheet(
            LabelBatchInput(page_type=PageType.VOLUME, year=2026, volume=2),
            "ARN",
        )
        self.assertEqual(sheet.label_count, T.labels_per_sheet)
        self.assertEqual(sheet.max_index, T.labels_per_sheet - 1)
        self.assertEqual(sheet.filename, "arn-2026-02.pdf")

    def test_build_continuation_sheet(self):
        sheet = services.build_sheet(
            LabelBatchInput(page_type=PageType.CONTINUATION), "ARN"
        )
        self.assertEqual(sheet.label_count, 189)

    def test_record_allocation_keeps_max(self):
        services.record_allocation(2026, 1, 100)
        services.record_allocation(2026, 1, 50)
        self.assertEqual(
            VolumeAllocation.objects.get(year=2026, volume=1).max_index, 100
        )
