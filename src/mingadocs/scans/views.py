"""Views for the scan intake workflow. See docs/scan-workflow.md."""
from __future__ import annotations

import datetime
import json
from collections import Counter

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import PageArnForm
from arnlabels.models import PrintSettings

from .models import Document, ScanBatch, ScanPage


def _page_json(page: ScanPage, arn_label: str | None = None) -> dict:
    arn = page.effective_arn
    human = arn.human_readable() if arn else ""
    return {
        "id": page.id,
        "position": page.position,
        "thumb_url": page.thumbnail.url if page.thumbnail else "",
        "image_url": page.image.url if page.image else "",
        "scan_status": page.scan_status,
        "ocr_status": page.ocr_status,
        "arn": human,
        # Display label: the ARN for a volume-start page, "page N" for a
        # continuation (its 1-based position within its document).
        "arn_label": human if arn_label is None else arn_label,
        "arn_source": page.arn_source,
        "ocr_note": page.ocr_note,
        "needs_attention": page.needs_attention,
        "detail_url": reverse("scans:page", args=[page.batch_id, page.id]),
    }


def _arn_labels(pages) -> dict[int, str]:
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


def _status_payload(batch: ScanBatch) -> dict:
    alerts = services.compute_alerts(batch)
    pages = list(batch.pages.all())
    labels = _arn_labels(pages)
    return {
        "status": batch.status,
        "scan_in_progress": services.scan_in_progress(batch),
        "pages": [_page_json(p, labels.get(p.id)) for p in pages],
        "alerts": [
            {"level": a.level, "page_id": a.page_id, "code": a.code,
             "message": a.message}
            for a in alerts
        ],
        "finalizable": services.finalizable(batch),
    }


def batch_list(request):
    return render(request, "scans/batch_list.html", {
        "nav": "scans",
        "active": ScanBatch.objects.exclude(status=ScanBatch.FINALIZED),
        "finalized": ScanBatch.objects.filter(status=ScanBatch.FINALIZED)[:10],
        "documents": Document.objects.all()[:10],
    })


def document_list(request):
    return render(request, "scans/document_list.html", {
        "nav": "documents", "documents": Document.objects.all(),
    })


@require_POST
def new_batch(request):
    batch = services.start_batch()
    return redirect("scans:console", batch_id=batch.id)


def batch_console(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    if batch.status == ScanBatch.REVIEW:
        return redirect("scans:review", batch_id=batch.id)
    if batch.status == ScanBatch.FINALIZED:
        messages.info(request, f"Batch #{batch.id} is finalized.")
        return redirect("scans:batch-list")
    return render(request, "scans/batch_console.html", {
        "nav": "scans", "batch": batch,
    })


def batch_review(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    if batch.status == ScanBatch.SCANNING:
        return redirect("scans:console", batch_id=batch.id)
    return render(request, "scans/batch_review.html", {
        "nav": "scans", "batch": batch,
        "initial": json.dumps(_status_payload(batch)),
    })


def batch_status(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    return JsonResponse(_status_payload(batch))


@require_POST
def scan_page(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        page = services.add_scan_page(batch)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    return JsonResponse({"page_id": page.id, "position": page.position})


@require_POST
def stop_batch(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    services.stop_batch(batch)
    url = reverse("scans:review", args=[batch.id])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"redirect": url})
    return redirect(url)


@require_POST
def discard_batch(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        services.discard_batch(batch)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    messages.success(request, f"Discarded batch #{batch_id}.")
    url = reverse("scans:batch-list")
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"redirect": url})
    return redirect(url)


@require_POST
def reorder(request, batch_id):
    batch = get_object_or_404(ScanBatch, pk=batch_id)
    try:
        ids = json.loads(request.body)["ids"]
        services.reorder(batch, [int(i) for i in ids])
    except (ValueError, KeyError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def finalize(request, batch_id):
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


def page_detail(request, batch_id, page_id):
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    prefix = PrintSettings.get_solo().arn_prefix
    manual_year = str(datetime.date.today().year)
    manual_volume = ""
    manual_index = ""
    if page.manual_arn.startswith(prefix):
        body = page.manual_arn[len(prefix):]
        if len(body) == 9 and body.isdigit():
            manual_year, manual_volume, manual_index = (
                body[:4], body[4:6], body[6:9],
            )
    if not manual_volume:
        # Pre-fill the volume from the other pages in the batch if a strict
        # majority of the resolved volume-start pages agree.
        vols = Counter()
        for other in page.batch.pages.all():
            a = other.effective_arn
            if a and not a.is_continuation:
                vols[a.body[4:6]] += 1
        if vols:
            top, n = vols.most_common(1)[0]
            if n * 2 > sum(vols.values()):
                manual_volume = top
    eff = page.effective_arn
    effective_label = _arn_labels(list(page.batch.pages.all())).get(page.id) or (
        eff.human_readable() if eff else ""
    )
    return render(request, "scans/page_detail.html", {
        "nav": "scans", "batch": page.batch, "page": page,
        "form": PageArnForm(),
        "config_prefix": prefix,
        "manual_year": manual_year,
        "manual_volume": manual_volume,
        "manual_index": manual_index,
        "effective_label": effective_label,
    })


@require_POST
def page_arn(request, batch_id, page_id):
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    form = PageArnForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    mode = form.cleaned_data["mode"]
    services.set_page_arn(
        page,
        arn=form.cleaned_data.get("arn", ""),
        continuation=(mode == PageArnForm.MODE_CONTINUATION),
        clear=(mode == PageArnForm.MODE_CLEAR),
    )
    page.refresh_from_db()
    pages = list(page.batch.pages.all())
    labels = _arn_labels(pages)
    return JsonResponse({
        "page": _page_json(page, labels.get(page.id)),
        "alerts": _status_payload(page.batch)["alerts"],
    })


@require_POST
def page_remove(request, batch_id, page_id):
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    services.remove_page(page)
    return JsonResponse({"ok": True})
