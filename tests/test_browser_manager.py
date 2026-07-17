import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.browser import (
    BrowserManager,
    _browser_path_candidates,
    _contains_winerror,
)


class BrowserManagerLifecycleTest(unittest.TestCase):
    def test_browser_path_candidates_include_windows_defaults(self):
        candidates = _browser_path_candidates('', 'chrome')
        self.assertEqual(candidates[0], 'chrome')
        if os.name == 'nt':
            self.assertTrue(any(path.lower().endswith('google\\chrome\\application\\chrome.exe')
                                for path in candidates[1:]))

    def test_explicit_browser_path_disables_fallbacks(self):
        self.assertEqual(
            _browser_path_candidates(r'C:\\custom\\chrome.exe', 'chrome'),
            [r'C:\\custom\\chrome.exe'],
        )

    def test_winerror_is_detected_through_exception_chain(self):
        cause = OSError(216, 'incompatible')
        error = RuntimeError('browser failed')
        error.__cause__ = cause
        self.assertTrue(_contains_winerror(error, 216))
        self.assertFalse(_contains_winerror(error, 193))

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows fallback behavior')
    def test_start_retries_known_chrome_path_after_winerror_216(self):
        calls = []

        class FakeOptions:
            browser_path = 'chrome'

            def auto_port(self):
                return self

            def set_timeouts(self, **kwargs):
                return self

            def set_argument(self, *args, **kwargs):
                return self

            def set_pref(self, *args, **kwargs):
                return self

            def set_user_data_path(self, path):
                return self

            def headless(self):
                return self

            def add_extension(self, path):
                return self

            def set_browser_path(self, path):
                self.browser_path = path
                return self

        class FakeChromium:
            def __init__(self, options):
                calls.append(options.browser_path)
                if len(calls) == 1:
                    raise OSError(216, 'incompatible')

            def get_tabs(self):
                return []

            def new_tab(self):
                return object()

            def quit(self, *args, **kwargs):
                return None

        fake_module = SimpleNamespace(Chromium=FakeChromium, ChromiumOptions=FakeOptions)
        manager = BrowserManager(headless=True)
        with patch.dict(sys.modules, {'DrissionPage': fake_module}):
            manager.start()
            manager.stop()

        self.assertEqual(calls[0], 'chrome')
        self.assertTrue(calls[1].lower().endswith('google\\chrome\\application\\chrome.exe'))

    def test_owned_temporary_profile_is_removed_on_stop(self):
        manager = BrowserManager()
        path = manager._prepare_user_data_path()
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(manager._owns_runtime_user_data)

        manager.stop()

        self.assertFalse(os.path.exists(path))
        self.assertIsNone(manager._runtime_user_data_path)

    def test_user_profile_is_preserved_on_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'persistent-profile')
            manager = BrowserManager(user_data_path=path)
            prepared = manager._prepare_user_data_path()
            manager.stop()

            self.assertEqual(prepared, os.path.abspath(path))
            self.assertTrue(os.path.isdir(path))

    def test_manager_has_no_stealth_mode(self):
        manager = BrowserManager()
        self.assertFalse(hasattr(manager, 'stealth'))
        self.assertFalse(hasattr(manager, '_apply_stealth_js'))


if __name__ == '__main__':
    unittest.main()
