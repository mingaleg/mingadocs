"""Cached access to the two slow external hardware probes used by the
settings page: the CUPS printer list and the SANE device list.

Both shell out / open a socket and can take many seconds (network scanners
especially). The settings page is otherwise cheap, so we probe **once per
process** and cache the result; the user refreshes it explicitly with the
"Rescan hardware" button. A long TTL is kept only as a safety net.
"""
from __future__ import annotations

from typing import Final

from django.core.cache import cache
from pydantic import TypeAdapter

_DEVICES_KEY: Final = "siteconfig:sane_devices"
_PRINTERS_KEY: Final = "siteconfig:cups_printers"
_TTL: Final = 60 * 60  # seconds

_STR_LIST: Final = TypeAdapter(list[str])


def _cached_list(key: str) -> list[str] | None:
    """Return a cached string list, or ``None`` if absent / corrupt."""
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        return _STR_LIST.validate_python(raw)
    except ValueError:
        return None


def sane_devices(*, refresh: bool = False) -> list[str]:
    if not refresh:
        cached = _cached_list(_DEVICES_KEY)
        if cached is not None:
            return cached
    from scans import scanner

    try:
        devices = scanner.list_devices()
    except Exception:  # noqa: BLE001 - degrade gracefully for the settings UI
        devices = []
    cache.set(_DEVICES_KEY, devices, _TTL)
    return devices


def cups_printers(*, refresh: bool = False) -> list[str]:
    if not refresh:
        cached = _cached_list(_PRINTERS_KEY)
        if cached is not None:
            return cached
    from arnlabels.printing import list_printers

    try:
        printers = sorted(list_printers())
    except Exception:  # noqa: BLE001 - CUPS unreachable
        printers = []
    cache.set(_PRINTERS_KEY, printers, _TTL)
    return printers
