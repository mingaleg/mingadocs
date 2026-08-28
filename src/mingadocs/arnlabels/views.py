"""Views: the label utility page and the print-settings page."""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from scans.enums import BatchStatus
from scans.models import Document, ScanBatch, ScanSettings

from . import printing, services
from .enums import OutputMode, PageType
from .forms import LabelBatchForm
from .models import PrintSettings, VolumeAllocation
from .services import LabelBatchInput


def index(request: HttpRequest) -> HttpResponse:
    """Landing page: current configuration and recent volume / scan activity."""
    config = PrintSettings.get_solo()
    active_batches = ScanBatch.objects.exclude(status=BatchStatus.FINALIZED)
    return render(
        request,
        "arnlabels/index.html",
        {
            "nav": "index",
            "config": config,
            "scan_config": ScanSettings.get_solo(),
            "template": services.current_template(),
            "recent": VolumeAllocation.objects.all()[:8],
            "active_batches": active_batches,
            "recent_batches": ScanBatch.objects.filter(
                status=BatchStatus.FINALIZED
            )[:5],
            "recent_documents": Document.objects.all()[:6],
        },
    )


def label_utility(request: HttpRequest) -> HttpResponse:
    """GET: show the batch form (volume fields auto-populated).
    POST: generate the sheet and either submit to CUPS or return a PDF."""
    config = PrintSettings.get_solo()

    if request.method == "POST":
        form = LabelBatchForm(request.POST)
        if form.is_valid():
            batch = LabelBatchInput.model_validate(form.cleaned_data)
            template = services.current_template()
            try:
                sheet = services.build_sheet(batch, config.arn_prefix)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                chosen = batch.output or (
                    OutputMode.PRINT if config.print_directly_by_default
                    else OutputMode.PDF
                )
                can_print = (
                    chosen is OutputMode.PRINT and bool(config.cups_printer)
                )

                if batch.page_type is PageType.VOLUME:
                    assert batch.year is not None and batch.volume is not None
                    services.record_allocation(
                        batch.year, batch.volume, sheet.max_index
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
        defaults = services.suggest_volume_defaults()
        form = LabelBatchForm(
            initial={
                "page_type": PageType.VOLUME.value,
                "year": defaults.year,
                "volume": defaults.volume,
            }
        )

    last_by_year: dict[int, dict[str, str]] = {}
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
                OutputMode.PRINT.value
                if config.print_directly_by_default and config.cups_printer
                else OutputMode.PDF.value
            ),
            "last_by_year": last_by_year,
        },
    )


def print_settings(request: HttpRequest) -> HttpResponse:
    """Old URL — label settings now live on the unified settings page."""
    return redirect(reverse("siteconfig:settings") + "#labels")
