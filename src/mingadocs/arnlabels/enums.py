"""Enumerated vocabulary for the label-printing side of the app."""
from __future__ import annotations

from enum import StrEnum


class PageType(StrEnum):
    """Which kind of label sheet the user is generating."""

    VOLUME = "volume"          # starts new documents
    CONTINUATION = "continuation"  # extra sheets, all the continuation ARN


class OutputMode(StrEnum):
    """What to do with a generated sheet."""

    PRINT = "print"
    PDF = "pdf"
