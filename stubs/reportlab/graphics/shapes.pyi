"""``reportlab.graphics.shapes`` — only ``Drawing.drawOn`` is used here."""

from reportlab.pdfgen.canvas import Canvas

class Drawing:
    width: float
    height: float
    def drawOn(
        self, canvas: Canvas, x: float, y: float, showBoundary: bool = ...
    ) -> None: ...
