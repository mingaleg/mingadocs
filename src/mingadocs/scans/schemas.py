"""Pydantic models for the scan workflow's JSON boundary.

The console and review pages poll ``GET /scans/<id>/status/`` and post edits;
every request body and response payload is one of these models, so nothing
crosses the wire as an untyped ``dict``.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .enums import AlertCode, AlertLevel, ArnSource, BatchStatus, OcrStatus, ScanStatus

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class PageState(BaseModel):
    model_config = _FROZEN

    id: int
    position: int
    thumb_url: str
    image_url: str
    scan_status: ScanStatus
    ocr_status: OcrStatus
    arn: str
    # Display label: the ARN for a volume-start page, "page N" for a
    # continuation (its 1-based position within its document).
    arn_label: str
    arn_source: ArnSource
    ocr_note: str
    needs_attention: bool
    detail_url: str


class AlertState(BaseModel):
    model_config = _FROZEN

    level: AlertLevel
    page_id: int | None
    code: AlertCode
    message: str


class BatchState(BaseModel):
    model_config = _FROZEN

    status: BatchStatus
    scan_in_progress: bool
    pages: list[PageState]
    alerts: list[AlertState]
    finalizable: bool


class PageArnResponse(BaseModel):
    model_config = _FROZEN

    page: PageState
    alerts: list[AlertState]


class ScanPageStarted(BaseModel):
    model_config = _FROZEN

    page_id: int
    position: int


class ReorderRequest(BaseModel):
    model_config = _FROZEN

    ids: list[int]


class DocumentThumbUrls(BaseModel):
    model_config = _FROZEN

    urls: list[str]


class ThumbnailRegenState(BaseModel):
    model_config = _FROZEN

    running: bool
    processed: int
    failed: int
    total: int
