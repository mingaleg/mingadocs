"""In-process background workers for scanning and OCR.

The physical scanner is a serial resource, so scans run one at a time
(``_SCAN_POOL`` has a single worker). OCR is CPU-bound image work and runs in a
small separate pool so a slow decode never blocks the next scan.

Job state is persisted on ``ScanPage`` rows; nothing here needs a broker. On
process restart :func:`recover_stale` marks interrupted work as failed so the
UI unblocks (a half-scanned page is never silently re-scanned).
"""
from __future__ import annotations

import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from django.core.files.base import ContentFile
from django.db import close_old_connections
from PIL import Image

from arnlabels.models import PrintSettings

from . import ocr, scanner
from .models import ScanBatch, ScanPage, ScanSettings

log = logging.getLogger("scans")

_SCAN_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scan")
_OCR_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")

THUMB_WIDTH = 320


def enqueue_scan(page_id: int) -> None:
    _SCAN_POOL.submit(_task, _run_scan, page_id)


def enqueue_ocr(page_id: int) -> None:
    _OCR_POOL.submit(_task, _run_ocr, page_id)


def _task(fn: Callable[[int], None], page_id: int) -> None:
    """Wrapper: never let a worker thread die silently, always tidy up conns."""
    try:
        fn(page_id)
    except Exception:  # noqa: BLE001
        log.exception("scan job %s failed for page %s", fn.__name__, page_id)
    finally:
        close_old_connections()


def _run_scan(page_id: int) -> None:
    page = ScanPage.objects.select_related("batch").get(pk=page_id)
    cfg = ScanSettings.get_solo()
    try:
        image_bytes = scanner.scan_page(cfg)
    except scanner.ScannerError as exc:
        ScanPage.objects.filter(pk=page_id).update(
            scan_status=ScanPage.SCAN_FAILED,
            ocr_status=ScanPage.OCR_FAILED,
            ocr_note=str(exc)[:200],
        )
        return

    with Image.open(io.BytesIO(image_bytes)) as im:
        im.load()
        width, height = im.size
        thumb = im.convert("RGB")
        thumb.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 4))
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=80)

    page.image.save(f"page-{page_id}.png", ContentFile(image_bytes), save=False)
    page.thumbnail.save(
        f"page-{page_id}-thumb.jpg", ContentFile(thumb_buf.getvalue()), save=False
    )
    page.width = width
    page.height = height
    page.scan_status = ScanPage.SCAN_DONE
    page.save(update_fields=[
        "image", "thumbnail", "width", "height", "scan_status"
    ])
    enqueue_ocr(page_id)


def _run_ocr(page_id: int) -> None:
    page = ScanPage.objects.get(pk=page_id)
    if not page.image:
        return
    ScanPage.objects.filter(pk=page_id).update(ocr_status=ScanPage.OCR_RUNNING)

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
                ocr_status=ScanPage.OCR_TIMEOUT, ocr_note="OCR timed out"
            )
            return
        except Exception as exc:  # noqa: BLE001
            ScanPage.objects.filter(pk=page_id).update(
                ocr_status=ScanPage.OCR_FAILED, ocr_note=str(exc)[:200]
            )
            return

    ScanPage.objects.filter(pk=page_id).update(
        ocr_status=ScanPage.OCR_DONE,
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
        batch__status=ScanBatch.SCANNING, scan_status=ScanPage.SCAN_PENDING
    ).update(
        scan_status=ScanPage.SCAN_FAILED,
        ocr_status=ScanPage.OCR_FAILED,
        ocr_note=note,
    )
    running = ScanPage.objects.filter(
        ocr_status=ScanPage.OCR_RUNNING
    ).update(ocr_status=ScanPage.OCR_FAILED, ocr_note=note)
    if pending or running:
        log.info("recover_stale: %s pending scans, %s running OCR reset",
                 pending, running)
