from django.apps import AppConfig


class ScansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scans"

    def ready(self) -> None:
        # Reset scan/OCR work orphaned by a restart. Deferred to the first
        # request so we never touch the DB during app initialization.
        from django.core.signals import request_started

        def _recover(*args, **kwargs):
            request_started.disconnect(_recover, dispatch_uid="scans_recover_stale")
            try:
                from . import jobs
                jobs.recover_stale()
            except Exception:  # noqa: BLE001 - never break request handling
                pass

        request_started.connect(
            _recover, weak=False, dispatch_uid="scans_recover_stale"
        )
