"""Business logic for scan batches: lifecycle, alerts, finalization."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Final

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image

from arnlabels.arn import Arn
from arnlabels.models import PrintSettings

from . import jobs
from .enums import AlertCode, AlertLevel, ArnMode, BatchStatus, ScanStatus
from .models import Document, ScanBatch, ScanPage

POSITION_STEP: Final = 10


def start_batch() -> ScanBatch:
    return ScanBatch.objects.create(status=BatchStatus.SCANNING)


def scan_in_progress(batch: ScanBatch) -> bool:
    """True while a scan is physically running for this batch.

    The button re-enables as soon as the scan finishes, even if OCR is still
    pending for that page.
    """
    return batch.pages.filter(scan_status=ScanStatus.PENDING).exists()


def add_scan_page(batch: ScanBatch) -> ScanPage:
    if batch.status_enum is not BatchStatus.SCANNING:
        raise ValueError("batch is not scanning")
    if scan_in_progress(batch):
        raise ValueError("a scan is already in progress")
    last = batch.pages.order_by("-position").first()
    position = (last.position + POSITION_STEP) if last else POSITION_STEP
    page = ScanPage.objects.create(batch=batch, position=position)
    jobs.enqueue_scan(page.id)
    return page


def stop_batch(batch: ScanBatch) -> None:
    if batch.status_enum is not BatchStatus.SCANNING:
        return
    batch.status = BatchStatus.REVIEW
    batch.stopped_at = timezone.now()
    batch.save(update_fields=["status", "stopped_at"])


@transaction.atomic
def discard_batch(batch: ScanBatch) -> None:
    """Hard-delete a non-finalized batch and every scanned page + image file."""
    if batch.status_enum is BatchStatus.FINALIZED:
        raise ValueError("a finalized batch cannot be discarded")
    for page in batch.pages.all():
        page.image.delete(save=False)
        page.thumbnail.delete(save=False)
    batch.delete()


def set_page_arn(page: ScanPage, mode: ArnMode, arn: str = "") -> None:
    """Apply a manual override to ``page``.

    * ``ArnMode.CLEAR``        — drop the override, fall back to detection
    * ``ArnMode.CONTINUATION`` — mark the page a continuation
    * ``ArnMode.SET``          — pin ``arn`` (raises ``ValueError`` if invalid)
    """
    if mode is ArnMode.CLEAR:
        page.manual_arn = ""
        page.manual_continuation = False
    elif mode is ArnMode.CONTINUATION:
        page.manual_arn = ""
        page.manual_continuation = True
    else:
        prefix = PrintSettings.get_solo().arn_prefix
        parsed = Arn.parse(arn, prefix)  # raises ValueError on bad input
        page.manual_arn = parsed.barcode_value()
        page.manual_continuation = False
    page.save(update_fields=["manual_arn", "manual_continuation"])


def remove_page(page: ScanPage) -> None:
    page.image.delete(save=False)
    page.thumbnail.delete(save=False)
    page.delete()


def reorder(batch: ScanBatch, ordered_ids: list[int]) -> None:
    pages = {p.id: p for p in batch.pages.all()}
    if set(ordered_ids) != set(pages):
        raise ValueError("reorder list must be a permutation of the batch pages")
    with transaction.atomic():
        for i, pid in enumerate(ordered_ids, start=1):
            ScanPage.objects.filter(pk=pid).update(position=i * POSITION_STEP)


# --- alerts ---------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    level: AlertLevel
    page_id: int | None
    code: AlertCode
    message: str


def compute_alerts(batch: ScanBatch) -> list[Alert]:
    alerts: list[Alert] = []
    pages = list(batch.pages.all())

    existing: set[str] = set(
        Document.objects.values_list("start_arn", flat=True)
    )
    seen_starts: dict[str, int] = {}
    open_document = False

    for page in pages:
        arn = page.effective_arn
        if arn is None:
            note = page.ocr_note or "no ARN detected"
            alerts.append(Alert(
                AlertLevel.ERROR, page.id, AlertCode.UNASSIGNED,
                f"Page {page.position}: {note} — set the ARN.",
            ))
            continue
        if arn.is_continuation:
            if not open_document:
                alerts.append(Alert(
                    AlertLevel.ERROR, page.id, AlertCode.ORPHAN_CONTINUATION,
                    f"Page {page.position} is a continuation with no document "
                    f"started before it.",
                ))
            continue
        # volume-start ARN
        open_document = True
        value = arn.barcode_value()
        if value in seen_starts:
            alerts.append(Alert(
                AlertLevel.ERROR, page.id, AlertCode.DUPLICATE_IN_BATCH,
                f"Page {page.position}: {arn.human_readable()} is also on "
                f"page {seen_starts[value]}.",
            ))
        else:
            seen_starts[value] = page.position
        if value in existing:
            alerts.append(Alert(
                AlertLevel.ERROR, page.id, AlertCode.CONFLICT_EXISTING,
                f"Page {page.position}: a document "
                f"{arn.human_readable()} already exists.",
            ))

    return alerts


def finalizable(batch: ScanBatch) -> bool:
    return (
        batch.status_enum is BatchStatus.REVIEW
        and batch.pages.exists()
        and not compute_alerts(batch)
    )


# --- finalize ----------------------------------------------------------------

def _pages_to_pdf(pages: list[ScanPage]) -> bytes:
    images: list[Image.Image] = []
    for page in pages:
        im = Image.open(page.image.open("rb"))
        im.load()
        images.append(im.convert("RGB"))
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    return buf.getvalue()


@dataclass
class _DocumentGroup:
    start: Arn
    pages: list[ScanPage] = field(default_factory=list)


@transaction.atomic
def finalize_batch(batch: ScanBatch) -> list[Document]:
    if not finalizable(batch):
        raise ValueError("batch has unresolved alerts or no pages")

    pages = list(batch.pages.all())
    groups: list[_DocumentGroup] = []
    for page in pages:
        arn = page.effective_arn
        if arn is None:  # unreachable: finalizable() rules this out
            raise ValueError(f"page {page.position} has no effective ARN")
        if arn.is_continuation:
            groups[-1].pages.append(page)
        else:
            groups.append(_DocumentGroup(start=arn, pages=[page]))

    documents: list[Document] = []
    for group in groups:
        pdf_bytes = _pages_to_pdf(group.pages)
        start = group.start.barcode_value()
        doc = Document.objects.create(
            start_arn=start, page_count=len(group.pages), batch=batch,
        )
        doc.pdf.save(f"{start}.pdf", ContentFile(pdf_bytes), save=False)
        first_thumb = group.pages[0].thumbnail
        if first_thumb:
            with first_thumb.open("rb") as fh:
                doc.thumbnail.save(
                    f"{start}-thumb.jpg", ContentFile(fh.read()), save=False,
                )
        doc.save()
        documents.append(doc)

    for page in pages:
        page.image.delete(save=False)
        page.thumbnail.delete(save=False)
    batch.pages.all().delete()

    batch.status = BatchStatus.FINALIZED
    batch.finalized_at = timezone.now()
    batch.save(update_fields=["status", "finalized_at"])
    return documents
