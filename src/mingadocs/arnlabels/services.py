"""Glue between the request layer and the arn/pdf/printing modules."""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from .arn import continuation_page_arns, volume_page_arns
from .enums import OutputMode, PageType
from .label_templates import TEMPLATES, LabelTemplate
from .models import VolumeAllocation
from .pdf import render_sheet


def current_template() -> LabelTemplate:
    return TEMPLATES[settings.LABEL_TEMPLATE]


def latest_volume(year: int) -> VolumeAllocation | None:
    """Most recent volume allocation recorded for ``year`` (or None)."""
    return (
        VolumeAllocation.objects.filter(year=year).order_by("-volume").first()
    )


class VolumeDefaults(BaseModel):
    """Auto-population for the volume-page form (all user-overridable)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int
    volume: int


def suggest_volume_defaults() -> VolumeDefaults:
    year = timezone.localdate().year
    last = latest_volume(year)
    return VolumeDefaults(
        year=year,
        volume=0 if last is None else last.volume + 1,
    )


class LabelBatchInput(BaseModel):
    """The whole ``LabelBatchForm`` after validation, as typed data."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    page_type: PageType
    year: int | None = None
    volume: int | None = None
    output: OutputMode | None = None


@dataclass(frozen=True)
class Sheet:
    pdf_bytes: bytes
    filename: str
    label_count: int
    max_index: int


def build_sheet(request: LabelBatchInput, prefix: str) -> Sheet:
    """Build one full sheet. The document index always runs 0..sheet capacity,
    so ``max_index`` is dictated by the label template, not the user."""
    template = current_template()
    max_index = template.labels_per_sheet - 1

    if request.page_type is PageType.VOLUME:
        if request.year is None or request.volume is None:
            raise ValueError("a volume page needs a year and a volume")
        arns = volume_page_arns(prefix, request.year, request.volume, max_index)
        filename = f"arn-{request.year}-{request.volume:02d}.pdf"
    else:
        arns = continuation_page_arns(prefix, template.labels_per_sheet)
        filename = "arn-continuation.pdf"

    return Sheet(
        pdf_bytes=render_sheet(template, arns),
        filename=filename,
        label_count=len(arns),
        max_index=max_index,
    )


def record_allocation(year: int, volume: int, max_index: int) -> None:
    obj, created = VolumeAllocation.objects.get_or_create(
        year=year, volume=volume, defaults={"max_index": max_index}
    )
    if not created and max_index > obj.max_index:
        obj.max_index = max_index
        obj.save(update_fields=["max_index"])
