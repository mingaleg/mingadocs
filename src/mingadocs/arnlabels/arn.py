"""ARN (Archive Serial Number) grammar and formatting.

An ARN is ``<prefix> <body>`` where ``<body>`` is 9 digits:

* Volume start:  ``YYYYVVNNN`` -> year (4), volume (2), index (3)
* Continuation:  ``000000000`` (9 zeros)

The barcode encodes the ARN *without* separators; the spaces are only a visual
aid in the human-readable line, which is grouped ``<prefix> <year> <volume>
<index>`` for a volume start (``<prefix> <body>`` for a continuation).

See ``docs/arn-labels.md``.
"""
from __future__ import annotations

import dataclasses
from typing import Final

from pydantic import field_validator, model_validator
from pydantic.dataclasses import dataclass

CONTINUATION_BODY: Final = "0" * 9
_BODY_LEN: Final = 9

YEAR_MIN: Final = 1000
YEAR_MAX: Final = 9999
VOLUME_MAX: Final = 99
INDEX_MAX: Final = 999


@dataclasses.dataclass(frozen=True)
class ArnParts:
    """The decoded fields of a volume-start ARN body."""

    year: int
    volume: int
    index: int


@dataclass(frozen=True)
class Arn:
    prefix: str
    body: str  # exactly 9 digits

    @field_validator("body")
    @classmethod
    def _body_is_nine_digits(cls, value: str) -> str:
        if len(value) != _BODY_LEN or not value.isdigit():
            raise ValueError(f"ARN body must be 9 digits, got {value!r}")
        return value

    @model_validator(mode="after")
    def _prefix_not_empty(self) -> Arn:
        if not self.prefix:
            raise ValueError("ARN prefix must not be empty")
        return self

    @classmethod
    def volume_start(cls, prefix: str, year: int, volume: int, index: int) -> Arn:
        if not YEAR_MIN <= year <= YEAR_MAX:
            raise ValueError(f"year must be 4 digits, got {year}")
        if not 0 <= volume <= VOLUME_MAX:
            raise ValueError(f"volume must be 0..{VOLUME_MAX}, got {volume}")
        if not 0 <= index <= INDEX_MAX:
            raise ValueError(f"index must be 0..{INDEX_MAX}, got {index}")
        return cls(prefix, f"{year:04d}{volume:02d}{index:03d}")

    @classmethod
    def continuation(cls, prefix: str) -> Arn:
        return cls(prefix, CONTINUATION_BODY)

    @classmethod
    def parse(cls, value: str, prefix: str) -> Arn:
        """Parse a raw barcode string (``prefix`` + 9 digits, no space).

        Raises ``ValueError`` if it does not start with ``prefix`` or the
        remainder is not exactly 9 digits.
        """
        value = value.strip()
        if not prefix or not value.startswith(prefix):
            raise ValueError(f"{value!r} does not start with prefix {prefix!r}")
        return cls(prefix, value[len(prefix):])

    @property
    def is_continuation(self) -> bool:
        return self.body == CONTINUATION_BODY

    @property
    def parts(self) -> ArnParts | None:
        """Decoded year / volume / index, or ``None`` for a continuation."""
        if self.is_continuation:
            return None
        return ArnParts(
            year=int(self.body[:4]),
            volume=int(self.body[4:6]),
            index=int(self.body[6:]),
        )

    def barcode_value(self) -> str:
        """Value encoded in Code 128 (no separators)."""
        return f"{self.prefix}{self.body}"

    def human_readable(self) -> str:
        """Text shown to people (under stickers, in the web UI).

        Volume start is grouped ``<prefix> <year> <volume> <index>``; a
        continuation stays ``<prefix> <body>`` (it has no such structure).
        The barcode value is unaffected — see ``barcode_value``.
        """
        parts = self.parts
        if parts is None:
            return f"{self.prefix} {self.body}"
        return (
            f"{self.prefix} {parts.year:04d} "
            f"{parts.volume:02d} {parts.index:03d}"
        )


def volume_page_arns(
    prefix: str, year: int, volume: int, max_index: int
) -> list[Arn]:
    """All ARNs for a volume page: index 0..max_index inclusive."""
    return [
        Arn.volume_start(prefix, year, volume, i) for i in range(max_index + 1)
    ]


def continuation_page_arns(prefix: str, count: int) -> list[Arn]:
    """``count`` identical continuation ARNs (one per label on the sheet)."""
    return [Arn.continuation(prefix) for _ in range(count)]
