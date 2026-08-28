from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from scans import scanner

from . import probe
from .apps import _should_warm_on_boot, _warm


class SettingsPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        p = mock.patch.object(
            scanner, "list_devices", return_value=["escl:https://h:443"]
        )
        self.list_devices = p.start()
        self.addCleanup(p.stop)

    def test_lives_at_slash_settings(self):
        r = self.client.get("/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="labels"')
        self.assertContains(r, 'id="scanner"')

    def test_devices_probed_once_and_cached(self):
        for _ in range(3):
            self.client.get("/settings/")
        self.assertEqual(self.list_devices.call_count, 1)

    def test_rescan_reprobes_hardware(self):
        self.client.get("/settings/")
        r = self.client.post("/settings/", {"section": "rescan"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.list_devices.call_count, 2)

    def test_saves_scanner_section(self):
        r = self.client.post("/settings/", {
            "section": "scanner", "resolution_dpi": 600, "mode": "Gray",
            "ocr_timeout_seconds": 15, "sane_device": "escl:https://h:443",
        })
        self.assertEqual(r.status_code, 302)
        from scans.models import ScanSettings
        cfg = ScanSettings.get_solo()
        self.assertEqual(cfg.resolution_dpi, 600)
        self.assertEqual(cfg.sane_device, "escl:https://h:443")

    def test_old_urls_redirect_here(self):
        self.assertRedirects(self.client.get("/scans/settings/"), "/settings/",
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/labels/settings/"),
                             "/settings/#labels", fetch_redirect_response=False)

    def test_boot_warm_fills_cache_so_the_page_does_not_probe(self):
        _warm()
        self.assertEqual(self.list_devices.call_count, 1)
        self.assertEqual(probe.sane_devices(), ["escl:https://h:443"])
        for _ in range(3):
            self.client.get("/settings/")
        self.assertEqual(self.list_devices.call_count, 1)  # still warm


class BootWarmGuardTests(TestCase):
    def _guard(self, argv, env):
        with mock.patch("sys.argv", ["manage.py", *argv]), \
                mock.patch.dict("os.environ", env, clear=False):
            return _should_warm_on_boot()

    def test_runs_for_a_server(self):
        self.assertTrue(self._guard(["runserver"], {"RUN_MAIN": "true"}))

    def test_skips_the_autoreload_parent(self):
        self.assertFalse(self._guard(["runserver"], {"RUN_MAIN": ""}))

    def test_skips_management_commands(self):
        for cmd in ("test", "migrate", "makemigrations", "shell"):
            self.assertFalse(self._guard([cmd], {}))

    def test_env_opt_out(self):
        self.assertFalse(self._guard(
            ["runserver"],
            {"RUN_MAIN": "true", "MINGADOCS_SKIP_HARDWARE_PROBE": "1"},
        ))
