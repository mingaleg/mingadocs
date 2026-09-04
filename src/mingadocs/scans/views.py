"""Views for the scan intake workflow. See docs/scan-workflow.md."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from pydantic import ValidationError

from arnlabels.models import PrintSettings

from . import jobs, services
from .enums import BatchStatus
from .forms import PageArnForm
from .models import Document, ScanBatch, ScanPage
from .schemas import (
    AlertState,
    BatchState,
    DocumentThumbUrls,
    PageArnResponse,
    PageState,
    ReorderRequest,
    ScanPageStarted,
    ThumbnailRegenState,
)

_XHR: Final = "XMLHttpRequest"
# 5 columns x 10 rows.
THUMB_PAGE_SIZE: Final = 50


def _page_state(page: ScanPage, arn_label: str | None = None) -> PageState:
    arn = page.effective_arn
    human = arn.human_readable() if arn else ""
    return PageState(
        id=page.id,
        position=page.position,
        thumb_url=page.thumbnail.url if page.thumbnail else "",
        image_url=page.image.url if page.image else "",
        scan_status=page.scan_state,
        ocr_status=page.ocr_state,
        arn=human,
        arn_label=human if arn_label is None else arn_label,
        arn_source=page.arn_source,
        ocr_note=page.ocr_note,
        needs_attention=page.needs_attention,
        detail_url=reverse("scans:page", args=[page.batch_id, page.id]),
    )


def _arn_labels(pages: Iterable[ScanPage]) -> dict[int, str]:
    """Map page id -> display label, numbering continuation pages within a doc."""
    labels: dict[int, str] = {}
    doc_page = 0
    for page in pages:
        arn = page.effective_arn
        if arn is None:
            labels[page.id] = ""
        elif arn.is_continuation:
            doc_page += 1
            labels[page.id] = f"page {doc_page}"
        else:
            doc_page = 1
            labels[page.id] = arn.human_readable()
    return labels


def _alert_states(batch: ScanBatch) -> list[AlertState]:
    return [
        AlertState(level=a.level, page_id=a.page_id, code=a.code, message=a.message)
        for a in services.compute_alerts(batch)
    ]


def _batch_state(batch: ScanBatch) -> BatchState:
    pages = list(batch.pages.all())
    labels = _arn_labels(pages)
    return BatchState(
        status=batch.status_enum,
        scan_in_progress=services.scan_in_progress(batch),
        pages=[_page_state(p, labels.get(p.id)) for p in pages],
        alerts=_alert_states(batch),
        finalizable=services.finalizable(batch),
    )


def _is_xhr(request: HttpRequest) -> bool:
    return request.headers.get("x-requested-with") == _XHR


def batch_list(request: HttpRequest) -> HttpResponse:
    return render(request, "scans/batch_list.html", {
        "nav": "scans",
        "active": ScanBatch.objects.exclude(status=BatchStatus.FINALIZED),
        "finalized": ScanBatch.objects.filter(status=BatchStatus.FINALIZED)[:10],
        "documents": Document.objects.all()[:10],
    })


def document_list(request: HttpRequest) -> HttpResponse:
    view = "thumbnails" if request.GET.get("view") == "thumbnails" else "list"
    if view == "thumbnails":
        paginator = Paginator(Document.objects.all(), THUMB_PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(request, "scans/document_list.html", {
            "nav": "documents", "view": view, "page_obj": page_obj,
        })
    return render(request, "scans/document_list.html", {
        "nav": "documents", "view": view, "documents": Document.objects.all(),
    })


def document_thumb_urls(request: HttpRequest, page: int) -> HttpResponse:
    """Thumbnail URLs for one page of the grid, for the next-page prefetch."""
    paginator = Paginator(Document.objects.all(), THUMB_PAGE_SIZE)
    urls = (
        [d.thumbnail.url for d in paginator.page(page).object_list if d.thumbnail]
        if 1 <= page <= paginator.num_pages
        else []
    )
    return JsonResponse(DocumentThumbUrls(urls=urls).model_dump(mode="json"))


@require_POST
def thumbnails_regenerate(request: HttpRequest) -> HttpResponse:
    """Kick off a background pass rebuilding Document thumbnails from their PDF.

    Posted from the settings page; see ``jobs.enqueue_thumbnail_regen``.
    """
    only_missing = request.POST.get("scope") != "all"
    if jobs.enqueue_thumbnail_regen(only_missing=only_missing):
        messages.success(request, "Regenerating document thumbnails…")
    else:
        messages.info(request, "A thumbnail regeneration pass is already running.")
    return redirect(reverse("siteconfig:settings") + "#documents")


def thumbnails_regenerate_status(request: HttpRequest) -> HttpResponse:
    status = jobs.thumbnail_regen_status()
    state = ThumbnailRegenState(
        running=status.running, processed=status.processed,
        failed=status.failed, total=status.total,
    )
    return JsonResponse(state.model_dump(mode="json"))


@require_POST
def new_batch(request: HttpRequest) -> HttpResponse:
    batch = services.start_batch()
    return redirect("scans:console", batch_id=batch.id)


def batch_console(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    if batch.status_enum is BatchStatus.REVIEW:
        return redirect("scans:review", batch_id=batch.id)
    if batch.status_enum is BatchStatus.FINALIZED:
        messages.info(request, f"Batch #{batch.id} is finalized.")
        return redirect("scans:batch-list")
    return render(request, "scans/batch_console.html", {
        "nav": "scans", "batch": batch,
    })


def batch_review(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    if batch.status_enum is BatchStatus.SCANNING:
        return redirect("scans:console", batch_id=batch.id)
    return render(request, "scans/batch_review.html", {
        "nav": "scans", "batch": batch,
        "initial": _batch_state(batch).model_dump_json(),
    })


def batch_status(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    return JsonResponse(_batch_state(batch).model_dump(mode="json"))


@require_POST
def scan_page(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        page = services.add_scan_page(batch)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    started = ScanPageStarted(page_id=page.id, position=page.position)
    return JsonResponse(started.model_dump(mode="json"))


@require_POST
def stop_batch(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    services.stop_batch(batch)
    url = reverse("scans:review", args=[batch.id])
    if _is_xhr(request):
        return JsonResponse({"redirect": url})
    return redirect(url)


@require_POST
def discard_batch(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        services.discard_batch(batch)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    messages.success(request, f"Discarded batch #{batch_id}.")
    url = reverse("scans:batch-list")
    if _is_xhr(request):
        return JsonResponse({"redirect": url})
    return redirect(url)


@require_POST
def reorder(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        payload = ReorderRequest.model_validate_json(request.body)
        services.reorder(batch, payload.ids)
    except (ValidationError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def finalize(request: HttpRequest, batch_id: int) -> HttpResponse:
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        docs = services.finalize_batch(batch)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    messages.success(
        request,
        f"Finalized batch #{batch.id}: {len(docs)} document(s) created.",
    )
    return JsonResponse({"redirect": reverse("scans:batch-list")})


@dataclass(frozen=True)
class _ManualArnDefaults:
    """Pre-fill values for the manual-ARN form on the page-detail page."""

    year: str
    volume: str
    index: str


def _manual_defaults(page: ScanPage) -> _ManualArnDefaults:
    year = str(timezone.localdate().year)
    volume = ""
    index = ""

    override = page.effective_arn if page.manual_arn else None
    if override is not None:
        parts = override.parts
        if parts is not None:
            return _ManualArnDefaults(
                year=f"{parts.year:04d}",
                volume=f"{parts.volume:02d}",
                index=f"{parts.index:03d}",
            )

    # Pre-fill the volume from the other pages in the batch when a strict
    # majority of the resolved volume-start pages agree.
    volumes: Counter[int] = Counter()
    for other in page.batch.pages.all():
        arn = other.effective_arn
        if arn is not None and (parts := arn.parts) is not None:
            volumes[parts.volume] += 1
    if volumes:
        top, count = volumes.most_common(1)[0]
        if count * 2 > sum(volumes.values()):
            volume = f"{top:02d}"

    return _ManualArnDefaults(year=year, volume=volume, index=index)


def page_detail(request: HttpRequest, batch_id: int, page_id: int) -> HttpResponse:
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    prefix = PrintSettings.get_solo().arn_prefix
    defaults = _manual_defaults(page)
    eff = page.effective_arn
    effective_label = _arn_labels(list(page.batch.pages.all())).get(page.id) or (
        eff.human_readable() if eff else ""
    )
    return render(request, "scans/page_detail.html", {
        "nav": "scans", "batch": page.batch, "page": page,
        "form": PageArnForm(),
        "config_prefix": prefix,
        "manual_year": defaults.year,
        "manual_volume": defaults.volume,
        "manual_index": defaults.index,
        "effective_label": effective_label,
    })


@require_POST
def page_arn(request: HttpRequest, batch_id: int, page_id: int) -> HttpResponse:
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    form = PageArnForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    services.set_page_arn(page, form.arn_mode(), form.arn_value())
    page.refresh_from_db()
    labels = _arn_labels(page.batch.pages.all())
    response = PageArnResponse(
        page=_page_state(page, labels.get(page.id)),
        alerts=_alert_states(page.batch),
    )
    return JsonResponse(response.model_dump(mode="json"))


@require_POST
def page_remove(request: HttpRequest, batch_id: int, page_id: int) -> HttpResponse:
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    services.remove_page(page)
    return JsonResponse({"ok": True})
