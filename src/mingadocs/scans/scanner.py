"""Talk to the physical scanner by shelling out to SANE's ``scanimage``.

For development / tests without hardware, set ``MINGADOCS_FAKE_SCANNER`` to the
path of an image file; :func:`scan_page` then returns that file's bytes.
"""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ScanSettings

FAKE_SCANNER_ENV = "MINGADOCS_FAKE_SCANNER"


class ScannerError(RuntimeError):
    """Raised when a scan cannot be acquired."""


def list_devices() -> list[str]:
    """Best-effort list of SANE device names (``scanimage -L``).

    Network backends (escl / hpaio) make this slow, so give it a generous
    timeout and parse whatever came back regardless of exit status.
    """
    # Fixed argv; scanimage is a system tool resolved via PATH.
    argv = ["scanimage", "-L"]
    try:
        proc = subprocess.run(  # nosec B603
            argv, capture_output=True, text=True, timeout=90, check=False,
        )
    except Exception:  # noqa: BLE001 - degrade gracefully for the settings UI
        return []
    out = proc.stdout
    devices: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("device `") and "'" in line[8:]:
            name = line[8:].split("'", 1)[0]
            if name and name not in devices:
                devices.append(name)
    # Order by how likely each backend is to be a working document scanner:
    # escl/airscan (driverless) first, hpaio next, webcams (v4l) last.
    rank = {"escl": 0, "airscan": 0, "hpaio": 1}
    devices.sort(key=lambda n: rank.get(n.split(":", 1)[0], 2))
    return devices


def scan_page(cfg: ScanSettings) -> bytes:
    """Acquire one page as PNG bytes."""
    fake = os.environ.get(FAKE_SCANNER_ENV)
    if fake:
        try:
            with open(fake, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise ScannerError(f"fake scanner file unreadable: {exc}") from exc

    device = _resolve_device(cfg.sane_device)
    dev = ["-d", device]

    # Try with resolution+mode, then drop mode, then drop everything: backends
    # differ in which option names/values they accept, and a bad value fails
    # late with "sane_start: Invalid argument" rather than a parse error.
    opt_sets: list[list[str]] = []
    full: list[str] = []
    if cfg.resolution_dpi:
        full += [f"--resolution={cfg.resolution_dpi}"]
    if cfg.mode:
        full += [f"--mode={cfg.mode}"]
    if full:
        opt_sets.append(full)
    if cfg.resolution_dpi and cfg.mode:
        opt_sets.append([f"--resolution={cfg.resolution_dpi}"])
    opt_sets.append([])

    proc = None
    for opts in opt_sets:
        proc = _run(["scanimage", "--format=png", *dev, *opts])
        if proc.returncode == 0 and _looks_like_image(proc.stdout):
            return proc.stdout

    detail = "no output"
    if proc is not None:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "no output"
    raise ScannerError(f"scanimage failed: {detail}")


def _resolve_device(configured: str) -> str:
    """Return the SANE device to scan from.

    A blank setting means "auto", but SANE's default device on a machine with a
    webcam is often that webcam, so we only auto-pick when there is exactly one
    device. Zero or many → ask the user to choose one on the settings page.
    """
    if configured:
        return configured
    devices = list_devices()
    if len(devices) == 1:
        return devices[0]
    raise ScannerError(
        "no scanner selected — pick one on the Scan settings page "
        f"({len(devices)} devices found)"
    )


def _looks_like_image(data: bytes) -> bool:
    if not data:
        return False
    head = data.lstrip()[:64].lower()
    return not (head.startswith(b"<!doctype") or head.startswith(b"<html")
                or head.startswith(b"<?xml"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    # cmd is built by the caller from a fixed template plus validated config
    # values (device name, integer dpi, mode word) — never shell input.
    try:
        return subprocess.run(cmd, capture_output=True, timeout=300, check=False)  # nosec B603
    except FileNotFoundError as exc:
        raise ScannerError("scanimage not installed (sane-utils)") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScannerError("scanimage timed out") from exc
