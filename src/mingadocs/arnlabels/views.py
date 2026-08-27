"""Views: the label utility page and the print-settings page."""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from . import printing, services
from .forms import LabelBatchForm, PrintSettingsForm
from .models import PrintSettings
from .services import PAGE_VOLUME


def _printer_names() -> list[str]:
    try:
        return sorted(printing.list_printers())
    except Exception:  # CUPS unreachable - degrade gracefully
        return []


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
                        data["year"], data["volume"], data["max_index"]
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
                response["Content-Disposition"] = (
                    f'attachment; filename="{sheet.filename}"'
                )
                return response
    else:
        form = LabelBatchForm(
            initial={
                "page_type": PAGE_VOLUME,
                "output": "print" if config.print_directly_by_default else "pdf",
                **services.suggest_volume_defaults(),
            }
        )

    return render(
        request,
        "arnlabels/label_utility.html",
        {
            "form": form,
            "config": config,
            "template": services.current_template(),
        },
    )


def print_settings(request):
    """Edit the global PrintSettings singleton."""
    config = PrintSettings.get_solo()
    printers = _printer_names()

    if request.method == "POST":
        form = PrintSettingsForm(
            request.POST, instance=config, printers=printers
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("arnlabels:print-settings")
    else:
        form = PrintSettingsForm(instance=config, printers=printers)

    return render(
        request,
        "arnlabels/print_settings.html",
        {"form": form, "printers": printers},
    )
