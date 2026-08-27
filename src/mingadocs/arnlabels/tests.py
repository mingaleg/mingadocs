from django.test import TestCase

from .arn import Arn, continuation_page_arns, volume_page_arns
from .label_templates import AVERY_L4731REV as T
from .models import VolumeAllocation
from .pdf import render_sheet
from . import services


class ArnTests(TestCase):
    def test_volume_start_format(self):
        a = Arn.volume_start("ARN", 2026, 4, 42)
        self.assertEqual(a.body, "202604042")
        self.assertEqual(a.barcode_value(), "ARN202604042")
        self.assertEqual(a.human_readable(), "ARN 202604042")
        self.assertFalse(a.is_continuation)

    def test_continuation(self):
        a = Arn.continuation("X")
        self.assertEqual(a.body, "000000000")
        self.assertTrue(a.is_continuation)
        self.assertEqual(a.human_readable(), "X 000000000")

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
        sx, sy, sw, sh = T.safe_box(3, 4)
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

    def test_pages_ok(self):
        self.assertEqual(self.client.get("/labels/").status_code, 200)
        self.assertEqual(self.client.get("/labels/settings/").status_code, 200)

    def test_download_pdf(self):
        r = self.client.post(
            "/labels/",
            {"page_type": "continuation", "output": "pdf"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))


class ServiceTests(TestCase):
    def test_suggest_defaults_first_volume(self):
        d = services.suggest_volume_defaults()
        self.assertEqual(d["volume"], 0)
        self.assertEqual(d["max_index"], 188)

    def test_suggest_defaults_increments(self):
        year = services.suggest_volume_defaults()["year"]
        VolumeAllocation.objects.create(year=year, volume=3, max_index=188)
        self.assertEqual(services.suggest_volume_defaults()["volume"], 4)

    def test_build_volume_sheet(self):
        sheet = services.build_sheet(
            {"page_type": "volume", "year": 2026, "volume": 2, "max_index": 50},
            "ARN",
        )
        self.assertEqual(sheet.label_count, 51)
        self.assertEqual(sheet.filename, "arn-2026-02.pdf")

    def test_build_continuation_sheet(self):
        sheet = services.build_sheet({"page_type": "continuation"}, "ARN")
        self.assertEqual(sheet.label_count, 189)

    def test_record_allocation_keeps_max(self):
        services.record_allocation(2026, 1, 100)
        services.record_allocation(2026, 1, 50)
        self.assertEqual(
            VolumeAllocation.objects.get(year=2026, volume=1).max_index, 100
        )
