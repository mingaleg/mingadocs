"""Detect the ARN Code 128 barcode on a scanned page."""
from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass

import zxingcpp
from PIL import Image

_CODE128 = zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.Code128)


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

# This build of zxing-cpp stops scanning a page once it has found a symbol (it
# has no "read every barcode" mode), so on a page that also carries a Data
# Matrix or other code the small ARN Code 128 is often never located in the
# full image even though it decodes fine from a crop. Scan the whole page and
# then a grid of overlapping tiles, and union every Code 128 hit.
_TILES_X = 2
_TILES_Y = 3
_TILE_OVERLAP = 0.12


def _regions(img: Image.Image) -> Iterator[Image.Image]:
    yield img
    w, h = img.size
    ox, oy = int(w * _TILE_OVERLAP), int(h * _TILE_OVERLAP)
    for iy in range(_TILES_Y):
        for ix in range(_TILES_X):
            box = (
                max(0, w * ix // _TILES_X - ox),
                max(0, h * iy // _TILES_Y - oy),
                min(w, w * (ix + 1) // _TILES_X + ox),
                min(h, h * (iy + 1) // _TILES_Y + oy),
            )
            yield img.crop(box)


def _scan_code128(img: Image.Image, prefix: str) -> set[str]:
    found: set[str] = set()
    for region in _regions(img):
        for binarizer in _BINARIZERS:
            try:
                results = zxingcpp.read_barcodes(
                    region,
                    formats=_CODE128,
                    binarizer=binarizer,
                )
            except Exception:  # noqa: BLE001  # nosec B112
                continue  # one bad binarizer pass must not sink detection
            for r in results:
                if r.text.startswith(prefix):
                    found.add(r.text)
    return found
