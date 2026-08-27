"""Physical geometry of supported label sheets.

All measurements in millimetres. The Avery L4731REV values below were extracted
from the vendor's own layout SVG (see ``tools/extract_label_geometry.py``), not
guessed - trust them over datasheet round numbers.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelTemplate:
    key: str
    name: str
    media: str  # CUPS/IPP media name, e.g. "A4"
    page_width: float
    page_height: float
    columns: int
    rows: int
    label_width: float
    label_height: float
    margin_left: float
    margin_top: float
    column_gap: float
    row_gap: float
    corner_radius: float = 0.0
    # Content is kept this far inside the label edge (clears rounded corners /
    # printer registration drift). The vendor's "safe area" (#...-field-PF194)
    # was not in the saved SVG; this is a conservative default.
    safe_inset: float = 2.0
    # Printer-calibration nudge for the whole grid, in mm. Positive = up / left.
    # Compensates for the printer's non-printable margins clipping low rows.
    offset_x: float = 0.0
    offset_y: float = 0.0

    @property
    def labels_per_sheet(self) -> int:
        return self.columns * self.rows

    @property
    def column_pitch(self) -> float:
        return self.label_width + self.column_gap

    @property
    def row_pitch(self) -> float:
        return self.label_height + self.row_gap

    def label_origin(self, col: int, row: int) -> tuple[float, float]:
        """Bottom-left corner (x, y) of a label in mm, PDF origin bottom-left.

        ``col`` is 0..columns-1 (left to right); ``row`` is 0..rows-1
        (top to bottom).
        """
        if not 0 <= col < self.columns:
            raise ValueError(f"col out of range: {col}")
        if not 0 <= row < self.rows:
            raise ValueError(f"row out of range: {row}")
        x = self.margin_left + col * self.column_pitch - self.offset_x
        y = (
            self.page_height
            - self.margin_top
            - row * self.row_pitch
            - self.label_height
            + self.offset_y
        )
        return x, y

    def safe_box(self, col: int, row: int) -> tuple[float, float, float, float]:
        """Safe content area as ``(x, y, width, height)`` in mm (origin
        bottom-left), i.e. the label inset by ``safe_inset`` on every side."""
        x, y = self.label_origin(col, row)
        return (
            x + self.safe_inset,
            y + self.safe_inset,
            self.label_width - 2 * self.safe_inset,
            self.label_height - 2 * self.safe_inset,
        )

    def positions(self) -> Iterator[tuple[int, int, int]]:
        """Yield ``(index, col, row)`` in row-major fill order."""
        i = 0
        for row in range(self.rows):
            for col in range(self.columns):
                yield i, col, row
                i += 1


# Avery Zweckform L4731REV-25: A4, 189 labels/sheet, 7 x 27, 25.4 x 10 mm,
# 2 mm rounded corners. Geometry from the vendor layout SVG.
AVERY_L4731REV = LabelTemplate(
    key="AVERY_L4731REV",
    name="Avery Zweckform L4731REV-25",
    media="A4",
    page_width=210.0,
    page_height=297.0,
    columns=7,
    rows=27,
    label_width=25.4,
    label_height=10.0,
    margin_left=8.4667,
    margin_top=13.4938,
    column_gap=2.54,
    row_gap=0.0,
    corner_radius=2.0,
    safe_inset=1.5,
    offset_y=1.5,  # nudge grid up: printer clips the bottom rows otherwise
)

TEMPLATES = {t.key: t for t in (AVERY_L4731REV,)}
