"""In-process background workers for scanning, OCR and thumbnail regen.

The physical scanner is a serial resource, so scans run one at a time
(``_SCAN_POOL`` has a single worker). OCR is CPU-bound image work and runs in a
small separate pool so a slow decode never blocks the next scan. Thumbnail
regeneration (``_THUMB_POOL``) is a third, independent single-worker pool: a
bulk pass over every ``Document`` triggered from the settings page, unrelated
to live scanning.

Job state for scan/OCR is persisted on ``ScanPage`` rows; nothing here needs a
broker. On process restart :func:`recover_stale` marks interrupted work as
failed so the UI unblocks (a half-scanned page is never silently re-scanned).
Thumbnail-regen progress is transient, in-memory only (see
:class:`ThumbnailRegenStatus`) — a restart mid-pass just means running it
again.
"""
from __future__ import annotations

import dataclasses
import io
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Final

import pypdfium2 as pdfium
from django.core.files.base import ContentFile
from django.db import close_old_connections
from PIL import Image

from arnlabels.models import PrintSettings

from . import ocr, scanner
from .enums import BatchStatus, OcrStatus, ScanStatus
from .models import Document, ScanPage, ScanSettings

log = logging.getLogger("scans")

_SCAN_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scan")
_OCR_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")
_THUMB_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thumb-regen")

THUMB_WIDTH: Final = 320


def enqueue_scan(page_id: int) -> None:
    _SCAN_POOL.submit(_task, _run_scan, page_id)


def enqueue_ocr(page_id: int) -> None:
    _OCR_POOL.submit(_task, _run_ocr, page_id)


def _task(fn: Callable[[int], None], page_id: int) -> None:
    """Wrapper: never let a worker thread die silently, always tidy up conns."""
    try:
        fn(page_id)
    except Exception:
        log.exception("scan job %s failed for page %s", fn.__name__, page_id)
    finally:
        close_old_connections()


def _make_thumbnail_jpeg(im: Image.Image) -> bytes:
    thumb = im.convert("RGB")
    thumb.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 4))
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _run_scan(page_id: int) -> None:
    page = ScanPage.objects.select_related("batch").get(pk=page_id)
    cfg = ScanSettings.get_solo()
    try:
        image_bytes = scanner.scan_page(cfg)
    except scanner.ScannerError as exc:
        ScanPage.objects.filter(pk=page_id).update(
            scan_status=ScanStatus.FAILED,
            ocr_status=OcrStatus.FAILED,
            ocr_note=str(exc)[:200],
        )
        return

    with Image.open(io.BytesIO(image_bytes)) as im:
        im.load()
        width, height = im.size
        thumb_bytes = _make_thumbnail_jpeg(im)

    page.image.save(f"page-{page_id}.png", ContentFile(image_bytes), save=False)
    page.thumbnail.save(
        f"page-{page_id}-thumb.jpg", ContentFile(thumb_bytes), save=False
    )
    page.width = width
    page.height = height
    page.scan_status = ScanStatus.DONE
    page.save(update_fields=[
        "image", "thumbnail", "width", "height", "scan_status"
    ])
    enqueue_ocr(page_id)


def _run_ocr(page_id: int) -> None:
    page = ScanPage.objects.get(pk=page_id)
    if not page.image:
        return
    ScanPage.objects.filter(pk=page_id).update(ocr_status=OcrStatus.RUNNING)

    cfg = ScanSettings.get_solo()
    prefix = PrintSettings.get_solo().arn_prefix
    image_bytes = page.image.read()

    # Run the decode in a throwaway thread so a pathological image can't wedge
    # the OCR pool past the configured deadline.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="decode") as ex:
        fut = ex.submit(ocr.detect_arn, image_bytes, prefix)
        try:
            result = fut.result(timeout=cfg.ocr_timeout_seconds)
        except FutureTimeout:
            fut.cancel()
            ScanPage.objects.filter(pk=page_id).update(
                ocr_status=OcrStatus.TIMEOUT, ocr_note="OCR timed out"
            )
            return
        except Exception as exc:  # noqa: BLE001
            ScanPage.objects.filter(pk=page_id).update(
                ocr_status=OcrStatus.FAILED, ocr_note=str(exc)[:200]
            )
            return

    ScanPage.objects.filter(pk=page_id).update(
        ocr_status=OcrStatus.DONE,
        detected_arn=result.arn or "",
        ocr_note=result.note,
    )


def recover_stale() -> None:
    """Mark scan/OCR work interrupted by a restart as failed.

    A half-scanned page is never re-enqueued: that could double-feed a
    sheet-fed scanner. The batch stays usable; the user just re-scans.
    """
    note = "interrupted by server restart"
    pending = ScanPage.objects.filter(
        batch__status=BatchStatus.SCANNING, scan_status=ScanStatus.PENDING
    ).update(
        scan_status=ScanStatus.FAILED,
        ocr_status=OcrStatus.FAILED,
        ocr_note=note,
    )
    running = ScanPage.objects.filter(
        ocr_status=OcrStatus.RUNNING
    ).update(ocr_status=OcrStatus.FAILED, ocr_note=note)
    if pending or running:
        log.info("recover_stale: %s pending scans, %s running OCR reset",
                 pending, running)


# --- document thumbnail regeneration ----------------------------------------

@dataclasses.dataclass(frozen=True)
class ThumbnailRegenStatus:
    running: bool
    processed: int
    failed: int
    total: int


@dataclasses.dataclass
class _ThumbRegenState:
    running: bool = False
    processed: int = 0
    failed: int = 0
    total: int = 0


_thumb_lock = threading.Lock()
_thumb_state = _ThumbRegenState()


def thumbnail_regen_status() -> ThumbnailRegenStatus:
    with _thumb_lock:
        return ThumbnailRegenStatus(
            running=_thumb_state.running, processed=_thumb_state.processed,
            failed=_thumb_state.failed, total=_thumb_state.total,
        )


def enqueue_thumbnail_regen(*, only_missing: bool) -> bool:
    """Start a background pass rebuilding ``Document`` thumbnails from their PDF.

    Returns ``False`` (no-op) if a pass is already running.
    """
    with _thumb_lock:
        if _thumb_state.running:
            return False
        _thumb_state.running = True
        _thumb_state.processed = 0
        _thumb_state.failed = 0
        _thumb_state.total = 0
    _THUMB_POOL.submit(_run_thumbnail_regen, only_missing)
    return True


def _run_thumbnail_regen(only_missing: bool) -> None:
    try:
        docs = Document.objects.all()
        if only_missing:
            docs = docs.filter(thumbnail="")
        ids = list(docs.values_list("id", flat=True))
        with _thumb_lock:
            _thumb_state.total = len(ids)
        for doc_id in ids:
            ok = _regenerate_one_thumbnail(doc_id)
            with _thumb_lock:
                _thumb_state.processed += 1
                if not ok:
                    _thumb_state.failed += 1
    except Exception:
        log.exception("thumbnail regeneration pass failed")
    finally:
        with _thumb_lock:
            _thumb_state.running = False
        close_old_connections()


def _regenerate_one_thumbnail(doc_id: int) -> bool:
    try:
        doc = Document.objects.get(pk=doc_id)
        if not doc.pdf:
            return False
        with doc.pdf.open("rb") as fh:
            pdf_bytes = fh.read()
        first_page = pdfium.PdfDocument(pdf_bytes)[0]
        thumb_bytes = _make_thumbnail_jpeg(first_page.render(scale=1).to_pil())
        doc.thumbnail.delete(save=False)
        doc.thumbnail.save(
            f"{doc.start_arn}-thumb.jpg", ContentFile(thumb_bytes), save=True,
        )
        return True
    except Exception:
        log.exception("failed to regenerate thumbnail for document %s", doc_id)
        return False
