"""ARN (Archive Serial Number) grammar and formatting.

An ARN is ``<prefix> <body>`` where ``<body>`` is 9 digits:

* Volume start:  ``YYYYVVNNN`` -> year (4), volume (2), index (3)
* Continuation:  ``000000000`` (9 zeros)

The barcode encodes the ARN *without* the separating space; the space is only
a visual aid in the human-readable line printed under the barcode.

See ``docs/arn-labels.md``.
"""
from __future__ import annotations

from dataclasses import dataclass

CONTINUATION_BODY = "0" * 9


@dataclass(frozen=True)
class Arn:
    prefix: str
    body: str  # 9 digits

    def __post_init__(self) -> None:
        if len(self.body) != 9 or not self.body.isdigit():
            raise ValueError(f"ARN body must be 9 digits, got {self.body!r}")

    @classmethod
    def volume_start(cls, prefix: str, year: int, volume: int, index: int) -> "Arn":
        if not 1000 <= year <= 9999:
            raise ValueError(f"year must be 4 digits, got {year}")
        if not 0 <= volume <= 99:
            raise ValueError(f"volume must be 0..99, got {volume}")
        if not 0 <= index <= 999:
            raise ValueError(f"index must be 0..999, got {index}")
        return cls(prefix, f"{year:04d}{volume:02d}{index:03d}")

    @classmethod
    def continuation(cls, prefix: str) -> "Arn":
        return cls(prefix, CONTINUATION_BODY)

    @property
    def is_continuation(self) -> bool:
        return self.body == CONTINUATION_BODY

    def barcode_value(self) -> str:
        """Value encoded in Code 128 (no space)."""
        return f"{self.prefix}{self.body}"

    def human_readable(self) -> str:
        """Text printed under the barcode (space after prefix)."""
        return f"{self.prefix} {self.body}"


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
