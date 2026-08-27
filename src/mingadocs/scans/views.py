"""Views for the scan intake workflow. See docs/scan-workflow.md."""
from __future__ import annotations

import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import scanner, services
from .forms import PageArnForm, ScanSettingsForm
from arnlabels.models import PrintSettings

from .models import Document, ScanBatch, ScanPage, ScanSettings


def _page_json(page: ScanPage) -> dict:
    arn = page.effective_arn
    return {
        "id": page.id,
        "position": page.position,
        "thumb_url": page.thumbnail.url if page.thumbnail else "",
        "image_url": page.image.url if page.image else "",
        "scan_status": page.scan_status,
        "ocr_status": page.ocr_status,
        "arn": arn.human_readable() if arn else "",
        "arn_source": page.arn_source,
        "ocr_note": page.ocr_note,
        "needs_attention": page.needs_attention,
        "detail_url": reverse("scans:page", args=[page.batch_id, page.id]),
    }


def _status_payload(batch: ScanBatch) -> dict:
    alerts = services.compute_alerts(batch)
    return {
        "status": batch.status,
        "scan_in_progress": services.scan_in_progress(batch),
        "pages": [_page_json(p) for p in batch.pages.all()],
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
    return render(request, "scans/page_detail.html", {
        "nav": "scans", "batch": page.batch, "page": page,
        "form": PageArnForm(),
        "config_prefix": PrintSettings.get_solo().arn_prefix,
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
    return JsonResponse({
        "page": _page_json(page),
        "alerts": _status_payload(page.batch)["alerts"],
    })


@require_POST
def page_remove(request, batch_id, page_id):
    page = get_object_or_404(ScanPage, pk=page_id, batch_id=batch_id)
    services.remove_page(page)
    return JsonResponse({"ok": True})


def scan_settings(request):
    config = ScanSettings.get_solo()
    try:
        devices = scanner.list_devices()
    except Exception:  # noqa: BLE001
        devices = []
    if request.method == "POST":
        form = ScanSettingsForm(request.POST, instance=config, devices=devices)
        if form.is_valid():
            form.save()
            messages.success(request, "Scan settings saved.")
            return redirect("scans:settings")
    else:
        form = ScanSettingsForm(instance=config, devices=devices)
    return render(request, "scans/scan_settings.html", {
        "nav": "scans", "form": form, "devices": devices,
    })
