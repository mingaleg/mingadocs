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

    @classmethod
    def parse(cls, value: str, prefix: str) -> "Arn":
        """Parse a raw barcode string (``prefix`` + 9 digits, no space).

        Raises ``ValueError`` if it does not start with ``prefix`` or the
        remainder is not exactly 9 digits.
        """
        value = value.strip()
        if not prefix or not value.startswith(prefix):
            raise ValueError(f"{value!r} does not start with prefix {prefix!r}")
        body = value[len(prefix):]
        if len(body) != 9 or not body.isdigit():
            raise ValueError(f"ARN body must be 9 digits, got {body!r}")
        return cls(prefix, body)

    @property
    def is_continuation(self) -> bool:
        return self.body == CONTINUATION_BODY

    def barcode_value(self) -> str:
        """Value encoded in Code 128 (no space)."""
        return f"{self.prefix}{self.body}"

    def human_readable(self) -> str:
        """Text shown to people (under stickers, in the web UI).

        Volume start is grouped ``<prefix> <year> <volume> <index>``; a
        continuation stays ``<prefix> <body>`` (it has no such structure).
        The barcode value is unaffected — see ``barcode_value``.
        """
        if self.is_continuation:
            return f"{self.prefix} {self.body}"
        year, volume, index = self.body[:4], self.body[4:6], self.body[6:]
        return f"{self.prefix} {year} {volume} {index}"


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
