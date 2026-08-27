"""Data model for ARN label printing.

See ``docs/arn-labels.md`` for the full requirements and the ARN grammar.
"""
from __future__ import annotations

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from solo.models import SingletonModel


class PrintSettings(SingletonModel):
    """Global, permanent configuration for label printing.

    Stored as a single row; edited on the settings page / Django admin.
    """

    arn_prefix = models.CharField(
        max_length=16,
        default='ARN',
        help_text='Prefix prepended to every ARN. Printed with a space '
                  'separating it from the numeric body.',
    )
    cups_printer = models.CharField(
        max_length=255,
        blank=True,
        help_text='Name of the CUPS print queue to send jobs to. '
                  'Leave blank to force download-only.',
    )
    print_directly_by_default = models.BooleanField(
        default=True,
        help_text='If set, the print button submits to CUPS; otherwise it '
                  'returns a PDF download.',
    )

    class Meta:
        verbose_name = 'Print settings'

    def __str__(self) -> str:  # pragma: no cover - trivial
        return 'Print settings'


class VolumeAllocation(models.Model):
    """Record of every volume page that has been generated.

    Used to auto-suggest the next volume number for a given year. One row per
    (year, volume) that has been printed at least once.
    """

    year = models.PositiveIntegerField(
        validators=[MinValueValidator(1000), MaxValueValidator(9999)],
    )
    volume = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(99)],
    )
    max_index = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(999)],
        help_text='Highest document index printed on this volume page.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'volume'], name='unique_year_volume',
            ),
        ]
        ordering = ['-year', '-volume']

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f'{self.year}/{self.volume:02d}'
