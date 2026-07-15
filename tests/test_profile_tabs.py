import unittest

from core.register import RegistrationEngine


class FakeTab:
    def __init__(self, url, *, cookies=None, title='Page', dom=None):
        self.url = url
        self.title = title
        self._cookies = cookies or []
        self._dom = dom or {
            'href': url,
            'readyState': 'complete',
            'notices': [],
        }

    def cookies(self, all_domains=False, all_info=False):
        return self._cookies

    def run_js(self, script, *args):
        return self._dom


class FakeChromium:
    def __init__(self, tabs):
        self._tabs = tabs

    def get_tabs(self):
        return self._tabs


class FakeBrowserManager:
    def __init__(self, tabs, selected=None):
        self.browser = FakeChromium(tabs)
        self._page = selected or tabs[0]

    @property
    def page(self):
        return self._page


class ProfileTabDetectionTest(unittest.TestCase):
    def test_detects_success_url_in_another_tab_and_selects_it(self):
        signup = FakeTab('https://accounts.x.ai/sign-up?redirect=grok-com')
        grok = FakeTab('https://grok.com/')
        browser = FakeBrowserManager([signup, grok], selected=signup)
        engine = RegistrationEngine(None, browser, None, None, None)

        reason = engine._profile_completion_reason()

        self.assertEqual(reason, 'navigated-tab-2:https://grok.com/')
        self.assertIs(browser._page, grok)

    def test_detects_sso_cookie_in_non_selected_tab(self):
        signup = FakeTab('https://accounts.x.ai/sign-up')
        account = FakeTab(
            'https://accounts.x.ai/sign-up',
            cookies=[{'name': 'sso', 'value': 'secret-cookie-value'}],
        )
        browser = FakeBrowserManager([signup, account], selected=signup)
        engine = RegistrationEngine(None, browser, None, None, None)

        reason = engine._profile_completion_reason()

        self.assertEqual(reason, 'sso-cookie:19:tab-2')
        self.assertIs(browser._page, account)

    def test_tab_diagnostics_redact_email_and_keep_dom_state(self):
        tab = FakeTab(
            'https://accounts.x.ai/sign-up',
            dom={
                'href': 'https://accounts.x.ai/sign-up',
                'readyState': 'complete',
                'hasGivenName': False,
                'notices': ['Account user+1@example.com already exists'],
            },
        )
        browser = FakeBrowserManager([tab])
        engine = RegistrationEngine(None, browser, None, None, None)

        tabs, details = engine._collect_profile_tab_diagnostics()

        self.assertEqual(tabs, [tab])
        self.assertEqual(details['tab_count'], 1)
        self.assertEqual(
            details['tabs'][0]['dom']['notices'],
            ['Account <redacted-email> already exists'],
        )


if __name__ == '__main__':
    unittest.main()
