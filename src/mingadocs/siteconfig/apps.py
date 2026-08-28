"""Site-configuration app.

On boot it warms the hardware-probe cache (`siteconfig.probe`) in a daemon
thread, so the first visit to ``/settings/`` does not have to wait on
``scanimage -L`` / CUPS.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Final

from django.apps import AppConfig

_log = logging.getLogger("siteconfig")

SKIP_ENV: Final = "MINGADOCS_SKIP_HARDWARE_PROBE"

# Management commands during which shelling out to `scanimage` / CUPS would be
# pointless or harmful — `test` above all (it would probe on every run).
_NO_PROBE_COMMANDS: Final = frozenset({
    "test", "migrate", "makemigrations", "sqlmigrate", "showmigrations",
    "collectstatic", "shell", "dbshell", "check", "createsuperuser",
    "changepassword", "loaddata", "dumpdata", "flush",
    "makemessages", "compilemessages",
})


def _should_warm_on_boot() -> bool:
    if os.environ.get(SKIP_ENV):
        return False
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in _NO_PROBE_COMMANDS:
        return False
    # `runserver` forks an autoreload watcher + a worker; only the worker
    # (RUN_MAIN=true) should do the probing.
    return not (command == "runserver" and os.environ.get("RUN_MAIN") != "true")


def _warm() -> None:
    from . import probe

    try:
        probe.warm()
    except Exception:  # noqa: BLE001 - a boot-time probe must never crash a worker
        _log.warning("boot-time hardware probe failed", exc_info=True)


class SiteconfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "siteconfig"
    verbose_name = "Site configuration"

    def ready(self) -> None:
        if _should_warm_on_boot():
            threading.Thread(
                target=_warm, name="siteconfig-hw-probe", daemon=True,
            ).start()
