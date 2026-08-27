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
    manual_body = ""
    if page.manual_arn.startswith(prefix):
        manual_body = page.manual_arn[len(prefix):]
    eff = page.effective_arn
    effective_label = _arn_labels(list(page.batch.pages.all())).get(page.id) or (
        eff.human_readable() if eff else ""
    )
    return render(request, "scans/page_detail.html", {
        "nav": "scans", "batch": page.batch, "page": page,
        "form": PageArnForm(),
        "config_prefix": prefix,
        "manual_body": manual_body,
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


def settings_page(request):
    """Unified settings page: label printing + scanner, one section each."""
    from arnlabels.forms import PrintSettingsForm
    from arnlabels.printing import list_printers

    print_config = PrintSettings.get_solo()
    scan_config = ScanSettings.get_solo()

    try:
        printers = sorted(list_printers())
    except Exception:  # noqa: BLE001 - CUPS unreachable
        printers = []
    try:
        devices = scanner.list_devices()
    except Exception:  # noqa: BLE001
        devices = []

    section = request.POST.get("section") if request.method == "POST" else None

    if section == "labels":
        print_form = PrintSettingsForm(request.POST, instance=print_config,
                                       printers=printers)
        scan_form = ScanSettingsForm(instance=scan_config, devices=devices)
        if print_form.is_valid():
            print_form.save()
            messages.success(request, "Label settings saved.")
            return redirect(reverse("scans:settings") + "#labels")
    elif section == "scanner":
        scan_form = ScanSettingsForm(request.POST, instance=scan_config,
                                     devices=devices)
        print_form = PrintSettingsForm(instance=print_config, printers=printers)
        if scan_form.is_valid():
            scan_form.save()
            messages.success(request, "Scanner settings saved.")
            return redirect(reverse("scans:settings") + "#scanner")
    else:
        print_form = PrintSettingsForm(instance=print_config, printers=printers)
        scan_form = ScanSettingsForm(instance=scan_config, devices=devices)

    return render(request, "scans/settings.html", {
        "nav": "settings",
        "print_form": print_form, "printers": printers,
        "scan_form": scan_form, "devices": devices,
    })
