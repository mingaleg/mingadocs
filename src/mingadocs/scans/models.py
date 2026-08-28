"""Data model for the scan intake workflow.

See ``docs/scan-workflow.md`` for the states, the async scan/OCR model and the
alert/finalize rules.
"""
from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models
from solo.models import SingletonModel

from arnlabels.arn import Arn
from arnlabels.models import PrintSettings

from .enums import ArnSource, BatchStatus, OcrStatus, ScanStatus


class ScanSettings(SingletonModel):
    """Global, permanent scanner configuration."""

    sane_device = models.CharField(
        max_length=255,
        blank=True,
        help_text="SANE device name (from `scanimage -L`). Blank = SANE default.",
    )
    resolution_dpi = models.PositiveIntegerField(
        default=300, validators=[MinValueValidator(50)]
    )
    mode = models.CharField(
        max_length=32, default="Color", blank=True,
        help_text="scanimage --mode value, e.g. Color / Gray / Lineart. "
                  "Leave blank to use the backend default.",
    )
    ocr_timeout_seconds = models.PositiveIntegerField(
        default=20, validators=[MinValueValidator(1)]
    )

    class Meta:
        verbose_name = "Scan settings"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "Scan settings"


class ScanBatch(models.Model):
    status = models.CharField(
        max_length=16,
        choices=BatchStatus.choices,
        default=BatchStatus.SCANNING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Scan batches"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Batch #{self.pk} ({self.status})"

    @property
    def status_enum(self) -> BatchStatus:
        return BatchStatus(self.status)


class ScanPage(models.Model):
    batch = models.ForeignKey(
        ScanBatch, on_delete=models.CASCADE, related_name="pages"
    )
    position = models.PositiveIntegerField(
        help_text="Sort key within the batch; renumbered on reorder."
    )
    image = models.FileField(upload_to="scans/%Y/%m/", blank=True)
    thumbnail = models.FileField(upload_to="scans/%Y/%m/", blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    scan_status = models.CharField(
        max_length=16, choices=ScanStatus.choices, default=ScanStatus.PENDING,
    )
    ocr_status = models.CharField(
        max_length=16, choices=OcrStatus.choices, default=OcrStatus.PENDING,
    )

    detected_arn = models.CharField(
        max_length=64, blank=True,
        help_text="Raw barcode text (prefix + body, no space) as decoded.",
    )
    manual_arn = models.CharField(max_length=64, blank=True)
    manual_continuation = models.BooleanField(default=False)
    ocr_note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Page {self.position} of batch #{self.batch_id}"

    @property
    def scan_state(self) -> ScanStatus:
        return ScanStatus(self.scan_status)

    @property
    def ocr_state(self) -> OcrStatus:
        return OcrStatus(self.ocr_status)

    @property
    def effective_arn(self) -> Arn | None:
        """The ARN this page will use, or ``None`` if it still needs a human.

        Priority: manual continuation flag > manual ARN > detected ARN.
        """
        prefix = PrintSettings.get_solo().arn_prefix
        if self.manual_continuation:
            return Arn.continuation(prefix)
        for value in (self.manual_arn, self.detected_arn):
            if value:
                try:
                    return Arn.parse(value, prefix)
                except ValueError:
                    continue
        return None

    @property
    def arn_source(self) -> ArnSource:
        if self.manual_continuation or self.manual_arn:
            return ArnSource.MANUAL
        if self.detected_arn:
            return ArnSource.DETECTED
        return ArnSource.NONE

    @property
    def needs_attention(self) -> bool:
        return self.effective_arn is None


class Document(models.Model):
    """A finalized multi-page PDF built from a run of scanned pages."""

    start_arn = models.CharField(max_length=64)
    page_count = models.PositiveIntegerField()
    pdf = models.FileField(upload_to="documents/%Y/%m/")
    batch = models.ForeignKey(
        ScanBatch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["start_arn"], name="unique_start_arn"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.start_arn

    @property
    def human_start_arn(self) -> str:
        """`start_arn` grouped prefix / year / volume / index for display."""
        prefix = PrintSettings.get_solo().arn_prefix
        try:
            return Arn.parse(self.start_arn, prefix).human_readable()
        except ValueError:
            return self.start_arn
