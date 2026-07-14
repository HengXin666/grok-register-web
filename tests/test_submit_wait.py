import unittest
from unittest.mock import Mock

from core.register import (
    RegistrationEngine,
    is_xai_permission_denied,
    submit_is_in_flight,
)


class SubmitWaitTest(unittest.TestCase):
    def test_disabled_submit_button_is_in_flight_even_when_label_remains(self):
        self.assertTrue(submit_is_in_flight({
            'loading': False,
            'primaryDisabled': True,
            'primaryText': '完成注册',
        }))

    def test_enabled_button_without_spinner_is_not_in_flight(self):
        self.assertFalse(submit_is_in_flight({
            'loading': False,
            'primaryDisabled': False,
            'primaryText': '完成注册',
        }))

    def test_email_submit_waits_for_code_entry_page(self):
        browser = Mock()
        browser.run_js.return_value = {
            'ready': True,
            'error': '',
            'href': 'https://accounts.x.ai/sign-up',
        }
        engine = RegistrationEngine(None, browser, None, None, None)

        engine._wait_for_verification_request('user@example.com', timeout=1)

        browser.run_js.assert_called_once()

    def test_email_submit_surfaces_permission_denied(self):
        browser = Mock()
        browser.run_js.return_value = {
            'ready': False,
            'error': '[permission_denied] HTTP 403',
            'href': 'https://accounts.x.ai/sign-up',
        }
        engine = RegistrationEngine(None, browser, None, None, None)

        with self.assertRaisesRegex(
            Exception,
            r'xAI verification-code request rejected.*permission_denied.*403',
        ):
            engine._wait_for_verification_request(
                'user@example.com', timeout=1,
            )

    def test_identifies_xai_permission_denied_as_upstream_abort(self):
        self.assertTrue(is_xai_permission_denied(
            'xAI rejected request: [permission_denied] HTTP 403'
        ))
        self.assertFalse(is_xai_permission_denied(
            'Microsoft Graph mail failed: HTTP 403 (ErrorAccessDenied)'
        ))


if __name__ == '__main__':
    unittest.main()
