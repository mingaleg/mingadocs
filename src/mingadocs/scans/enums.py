"""Enumerated vocabulary for the scan-intake workflow.

DB-backed status fields use ``models.TextChoices`` (so Django gets ``.choices``);
the rest are plain ``StrEnum``. Every value is a ``str`` at runtime, so it drops
straight into JSON and template context.
"""
from __future__ import annotations

from enum import StrEnum

from django.db import models


class BatchStatus(models.TextChoices):
    SCANNING = "scanning", "Scanning"
    REVIEW = "review", "Ready for review"
    FINALIZED = "finalized", "Finalized"


class ScanStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class OcrStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"
    TIMEOUT = "timeout", "Timed out"


class ArnSource(StrEnum):
    """Where a page's effective ARN came from."""

    MANUAL = "manual"
    DETECTED = "detected"
    NONE = "none"


class ArnMode(StrEnum):
    """The edit the user asked for on the page-detail form."""

    SET = "arn"
    CONTINUATION = "continuation"
    CLEAR = "clear"


class OcrOutcome(StrEnum):
    """Result of scanning a page image for the ARN barcode."""

    FOUND = "found"          # exactly one matching Code 128
    NOT_FOUND = "not_found"  # zero
    AMBIGUOUS = "ambiguous"  # more than one


class AlertLevel(StrEnum):
    WARN = "warn"
    ERROR = "error"


class AlertCode(StrEnum):
    UNASSIGNED = "unassigned"
    ORPHAN_CONTINUATION = "orphan_continuation"
    DUPLICATE_IN_BATCH = "duplicate_in_batch"
    CONFLICT_EXISTING = "conflict_existing"
