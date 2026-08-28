"""``reportlab.graphics.barcode`` — the barcode-drawing factory."""

from reportlab.graphics.shapes import Drawing

def createBarcodeDrawing(codeName: str, **options: object) -> Drawing: ...
