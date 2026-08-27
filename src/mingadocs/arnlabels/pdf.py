"""Render a sheet of ARN labels to PDF with reportlab.

Each label carries a Code 128 barcode plus the human-readable ARN printed
underneath it. Layout comes from ``label_templates.LabelTemplate``: content is
confined to that template's safe area (label edge inset by ``safe_inset``).
"""
from __future__ import annotations

from io import BytesIO

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .arn import Arn
from .label_templates import LabelTemplate

TEXT_GAP_MM = 0.4
FONT_NAME = "Helvetica"
FONT_SIZE_PT = 5.5
# White margin left/right of the barcode, inside the safe area, so the outer
# bars are not clipped by label-edge / printer registration drift.
BARCODE_QUIET_MM = 1.2


def render_sheet(template: LabelTemplate, arns: list[Arn]) -> bytes:
    """Return PDF bytes for a single sheet.

    ``arns`` is filled row-major, left-to-right, top-to-bottom, and must not
    exceed ``template.labels_per_sheet``.
    """
    if len(arns) > template.labels_per_sheet:
        raise ValueError(
            f"{len(arns)} ARNs exceed sheet capacity "
            f"{template.labels_per_sheet}"
        )

    buf = BytesIO()
    c = canvas.Canvas(
        buf, pagesize=(template.page_width * mm, template.page_height * mm)
    )
    for index, col, row in template.positions():
        if index >= len(arns):
            break
        _draw_label(c, template.safe_box(col, row), arns[index])
    c.showPage()
    c.save()
    return buf.getvalue()


def _draw_label(
    c: canvas.Canvas,
    safe_box_mm: tuple[float, float, float, float],
    arn: Arn,
) -> None:
    sx, sy, sw, sh = (v * mm for v in safe_box_mm)
    text_h = FONT_SIZE_PT
    gap = TEXT_GAP_MM * mm
    barcode_h = sh - text_h - gap
    barcode_w = sw - 2 * BARCODE_QUIET_MM * mm

    drawing = createBarcodeDrawing(
        "Code128",
        value=arn.barcode_value(),
        width=barcode_w,
        height=barcode_h,
        humanReadable=False,
        quiet=False,
        barHeight=barcode_h,
    )
    drawing.drawOn(c, sx + (sw - barcode_w) / 2, sy + text_h + gap)

    # Grouped ARN (prefix / year / volume / index). Shrink the font if the
    # extra separators would overrun the safe width on a long prefix.
    text = arn.human_readable()
    size = FONT_SIZE_PT
    while size > 3.5 and c.stringWidth(text, FONT_NAME, size) > sw:
        size -= 0.25
    c.setFont(FONT_NAME, size)
    c.drawCentredString(sx + sw / 2, sy, text)


__all__ = ["render_sheet"]
