"""Glue between the request layer and the arn/pdf/printing modules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.conf import settings

from .arn import continuation_page_arns, volume_page_arns
from .label_templates import TEMPLATES
from .models import VolumeAllocation
from .pdf import render_sheet

PAGE_VOLUME = "volume"
PAGE_CONTINUATION = "continuation"


def current_template():
    return TEMPLATES[settings.LABEL_TEMPLATE]


def suggest_volume_defaults() -> dict:
    """Auto-population for the volume-page form (all user-overridable)."""
    template = current_template()
    year = date.today().year
    last = (
        VolumeAllocation.objects.filter(year=year).order_by("-volume").first()
    )
    volume = 0 if last is None else last.volume + 1
    return {
        "year": year,
        "volume": volume,
        "max_index": template.labels_per_sheet - 1,
    }


@dataclass
class Sheet:
    pdf_bytes: bytes
    filename: str
    label_count: int


def build_sheet(cleaned: dict, prefix: str) -> Sheet:
    template = current_template()
    if cleaned["page_type"] == PAGE_VOLUME:
        year = cleaned["year"]
        volume = cleaned["volume"]
        max_index = cleaned["max_index"]
        arns = volume_page_arns(prefix, year, volume, max_index)
        if len(arns) > template.labels_per_sheet:
            raise ValueError(
                f"max_index {max_index} needs {len(arns)} labels; sheet holds "
                f"{template.labels_per_sheet}."
            )
        filename = f"arn-{year}-{volume:02d}.pdf"
    else:
        arns = continuation_page_arns(prefix, template.labels_per_sheet)
        filename = "arn-continuation.pdf"

    return Sheet(
        pdf_bytes=render_sheet(template, arns),
        filename=filename,
        label_count=len(arns),
    )


def record_allocation(year: int, volume: int, max_index: int) -> None:
    obj, created = VolumeAllocation.objects.get_or_create(
        year=year, volume=volume, defaults={"max_index": max_index}
    )
    if not created and max_index > obj.max_index:
        obj.max_index = max_index
        obj.save(update_fields=["max_index"])
