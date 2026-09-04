"""The single, unified settings page (``/settings/``).

It edits two django-solo singletons that live in their own domain apps:
``arnlabels.PrintSettings`` (label printing) and ``scans.ScanSettings``
(scanner). The printer / device lists it offers are cached — see
:mod:`siteconfig.probe`.
"""
from __future__ import annotations

from enum import StrEnum

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from arnlabels.forms import PrintSettingsForm
from arnlabels.models import PrintSettings
from scans.forms import ScanSettingsForm
from scans.models import Document, ScanSettings

from . import probe


class SettingsSection(StrEnum):
    """Which part of the unified settings page a POST targets."""

    LABELS = "labels"
    SCANNER = "scanner"
    RESCAN = "rescan"


def _posted_section(request: HttpRequest) -> SettingsSection | None:
    if request.method != "POST":
        return None
    try:
        return SettingsSection(request.POST.get("section", ""))
    except ValueError:
        return None


def settings_page(request: HttpRequest) -> HttpResponse:
    """Label printing + scanner settings, one ``<section>`` each."""
    print_config = PrintSettings.get_solo()
    scan_config = ScanSettings.get_solo()
    section = _posted_section(request)

    if section is SettingsSection.RESCAN:
        probe.cups_printers(refresh=True)
        probe.sane_devices(refresh=True)
        messages.success(request, "Re-probed printers and scanners.")
        return redirect(reverse("siteconfig:settings") + "#scanner")

    printers = probe.cups_printers()
    devices = probe.sane_devices()

    if section is SettingsSection.LABELS:
        print_form = PrintSettingsForm(request.POST, instance=print_config,
                                       printers=printers)
        scan_form = ScanSettingsForm(instance=scan_config, devices=devices)
        if print_form.is_valid():
            print_form.save()
            messages.success(request, "Label settings saved.")
            return redirect(reverse("siteconfig:settings") + "#labels")
    elif section is SettingsSection.SCANNER:
        scan_form = ScanSettingsForm(request.POST, instance=scan_config,
                                     devices=devices)
        print_form = PrintSettingsForm(instance=print_config, printers=printers)
        if scan_form.is_valid():
            scan_form.save()
            messages.success(request, "Scanner settings saved.")
            return redirect(reverse("siteconfig:settings") + "#scanner")
    else:
        print_form = PrintSettingsForm(instance=print_config, printers=printers)
        scan_form = ScanSettingsForm(instance=scan_config, devices=devices)

    return render(request, "siteconfig/settings.html", {
        "nav": "settings",
        "print_form": print_form, "printers": printers,
        "scan_form": scan_form, "devices": devices,
        "doc_count": Document.objects.count(),
        "missing_thumb_count": Document.objects.filter(thumbnail="").count(),
    })
