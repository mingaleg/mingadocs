"""Talk to the physical scanner by shelling out to SANE's ``scanimage``.

For development / tests without hardware, set ``MINGADOCS_FAKE_SCANNER`` to the
path of an image file; :func:`scan_page` then returns that file's bytes.
"""
from __future__ import annotations

import os
import subprocess

FAKE_SCANNER_ENV = "MINGADOCS_FAKE_SCANNER"


class ScannerError(RuntimeError):
    """Raised when a scan cannot be acquired."""


def list_devices() -> list[str]:
    """Best-effort list of SANE device names (``scanimage -L``)."""
    try:
        out = subprocess.run(
            ["scanimage", "-L"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except Exception:  # noqa: BLE001 - degrade gracefully for the settings UI
        return []
    devices = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("device `") and "'" in line[8:]:
            devices.append(line[8:].split("'", 1)[0])
    return devices


def scan_page(cfg) -> bytes:
    """Acquire one page as PNG bytes. ``cfg`` is a ``ScanSettings`` instance."""
    fake = os.environ.get(FAKE_SCANNER_ENV)
    if fake:
        try:
            with open(fake, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise ScannerError(f"fake scanner file unreadable: {exc}") from exc

    cmd = [
        "scanimage",
        "--format=png",
        f"--resolution={cfg.resolution_dpi}",
        f"--mode={cfg.mode}",
    ]
    if cfg.sane_device:
        cmd += ["-d", cfg.sane_device]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
    except FileNotFoundError as exc:
        raise ScannerError("scanimage not installed (sane-utils)") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScannerError("scanimage timed out") from exc
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "no output"
        raise ScannerError(f"scanimage failed: {detail}")
    return proc.stdout
