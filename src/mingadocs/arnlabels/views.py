"""Views: the label utility page and the print-settings page."""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from scans.models import Document, ScanBatch

from . import printing, services
from .forms import LabelBatchForm
from .models import PrintSettings, VolumeAllocation
from .services import PAGE_VOLUME


def index(request):
    """Landing page: current configuration and recent volume / scan activity."""
    config = PrintSettings.get_solo()
    active_batches = ScanBatch.objects.exclude(status=ScanBatch.FINALIZED)
    return render(
        request,
        "arnlabels/index.html",
        {
            "nav": "index",
            "config": config,
            "template": services.current_template(),
            "suggestion": services.suggest_volume_defaults(),
            "recent": VolumeAllocation.objects.all()[:8],
            "active_batches": active_batches.count(),
            "scanning_batches": active_batches.filter(
                status=ScanBatch.SCANNING
            ).count(),
            "document_count": Document.objects.count(),
            "recent_documents": Document.objects.all()[:8],
        },
    )


def label_utility(request):
    """GET: show the batch form (volume fields auto-populated).
    POST: generate the sheet and either submit to CUPS or return a PDF."""
    config = PrintSettings.get_solo()

    if request.method == "POST":
        form = LabelBatchForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            template = services.current_template()
            try:
                sheet = services.build_sheet(data, config.arn_prefix)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                want_print = data.get("output") or (
                    "print" if config.print_directly_by_default else "pdf"
                )
                can_print = want_print == "print" and bool(config.cups_printer)

                if data["page_type"] == PAGE_VOLUME:
                    services.record_allocation(
                        data["year"], data["volume"], sheet.max_index
                    )

                if can_print:
                    job_id = printing.submit_pdf(
                        config.cups_printer,
                        sheet.pdf_bytes,
                        sheet.filename,
                        media=template.media,
                    )
                    messages.success(
                        request,
                        f"Sent {sheet.label_count} labels to "
                        f"'{config.cups_printer}' (job {job_id}).",
                    )
                    return redirect("arnlabels:label-utility")

                response = HttpResponse(
                    sheet.pdf_bytes, content_type="application/pdf"
                )
                # inline: show it in the browser's PDF viewer; the filename is
                # still used if the user then saves it.
                response["Content-Disposition"] = (
                    f'inline; filename="{sheet.filename}"'
                )
                return response
    else:
        form = LabelBatchForm(
            initial={
                "page_type": PAGE_VOLUME,
                **services.suggest_volume_defaults(),
            }
        )

    last_by_year = {}
    for a in VolumeAllocation.objects.order_by("year", "volume"):
        last_by_year[a.year] = {
            "volume": f"{a.volume:02d}",
            "created": a.created_at.strftime("%Y-%m-%d %H:%M"),
        }

    return render(
        request,
        "arnlabels/label_utility.html",
        {
            "nav": "labels",
            "form": form,
            "config": config,
            "template": services.current_template(),
            "can_print": bool(config.cups_printer),
            "default_output": (
                "print"
                if config.print_directly_by_default and config.cups_printer
                else "pdf"
            ),
            "last_by_year": last_by_year,
        },
    )


def print_settings(request):
    """Old URL — label settings now live on the unified settings page."""
    return redirect(reverse("scans:settings") + "#labels")
