"""Detect the ARN Code 128 barcode on a scanned page."""
from __future__ import annotations

import io
from dataclasses import dataclass

import zxingcpp
from PIL import Image


@dataclass
class OcrResult:
    arn: str | None          # decoded barcode text (prefix + body) or None
    note: str                # human-readable explanation when arn is None
    candidate_count: int      # matching Code 128 symbols found


def detect_arn(image_bytes: bytes, prefix: str) -> OcrResult:
    """Return the single ARN barcode on the page, if exactly one is present.

    Only Code 128 symbols whose text starts with ``prefix`` are considered.
    Zero or more than one match -> ``arn is None`` (page stays unassigned).
    """
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    matches = sorted(_scan_code128(img, prefix))
    if len(matches) == 1:
        return OcrResult(arn=matches[0], note="", candidate_count=1)
    if not matches:
        return OcrResult(arn=None, note="no ARN barcode found", candidate_count=0)
    return OcrResult(
        arn=None,
        note=f"{len(matches)} ARN barcodes found",
        candidate_count=len(matches),
    )


# zxing-cpp's default binarizer (LocalAverage) can miss a crisp Code 128 on a
# full-resolution flatbed scan that a fixed threshold reads fine, so we try
# several binarizers and union the Code 128 hits.
_BINARIZERS = (
    zxingcpp.Binarizer.LocalAverage,
    zxingcpp.Binarizer.FixedThreshold,
    zxingcpp.Binarizer.GlobalHistogram,
)


def _scan_code128(img: Image.Image, prefix: str) -> set[str]:
    found: set[str] = set()
    for binarizer in _BINARIZERS:
        try:
            results = zxingcpp.read_barcodes(
                img,
                formats=zxingcpp.BarcodeFormat.Code128,
                binarizer=binarizer,
            )
        except Exception:  # noqa: BLE001 - a bad pass must not sink detection
            continue
        for r in results:
            if r.text.startswith(prefix):
                found.add(r.text)
    return found
