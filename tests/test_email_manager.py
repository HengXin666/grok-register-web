import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from config import SCOPES
from core.email_manager import (
    EmailManager,
    EmailPermissionError,
)


class DummyDatabase:
    def __init__(self):
        self.updated_tokens = []

    def update_refresh_token(self, account_id, token):
        self.updated_tokens.append((account_id, token))


class EmailManagerGraphTest(unittest.TestCase):
    def setUp(self):
        self.db = DummyDatabase()
        self.manager = EmailManager(self.db)

    @patch('core.email_manager.requests.post')
    def test_legacy_token_uses_outlook_api_without_scope_override(self, post):
        response = Mock(status_code=200, text='')
        response.json.return_value = {
            'access_token': 'opaque-outlook-token',
            'refresh_token': 'rotated-refresh-token',
        }
        post.return_value = response
        self.manager._detect_mail_api = Mock(return_value=('outlook', ''))

        refresh_token, access_token, mail_api = self.manager.refresh_token(
            7, 'client-id', 'old-refresh-token',
        )

        self.assertEqual(refresh_token, 'rotated-refresh-token')
        self.assertEqual(access_token, 'opaque-outlook-token')
        self.assertEqual(mail_api, 'outlook')
        self.assertEqual(self.db.updated_tokens, [(7, 'rotated-refresh-token')])
        call = post.call_args
        self.assertEqual(call.args[0], 'https://login.live.com/oauth20_token.srf')
        self.assertNotIn('scope', call.kwargs['data'])

    @patch('core.email_manager.requests.post')
    def test_graph_scope_is_used_when_legacy_refresh_has_no_mail_access(self, post):
        denied_one = Mock(status_code=400, text='')
        denied_one.json.return_value = {'error': 'invalid_scope'}
        denied_two = Mock(status_code=400, text='')
        denied_two.json.return_value = {'error': 'invalid_scope'}
        granted = Mock(status_code=200, text='')
        granted.json.return_value = {'access_token': 'graph-access-token'}
        post.side_effect = [denied_one, denied_two, granted]
        self.manager._detect_mail_api = Mock(return_value=('graph', ''))

        _, access_token, mail_api = self.manager.refresh_token(
            7, 'client-id', 'old-refresh-token',
        )

        self.assertEqual(access_token, 'graph-access-token')
        self.assertEqual(mail_api, 'graph')
        third_call = post.call_args_list[2]
        self.assertEqual(
            third_call.args[0],
            'https://login.microsoftonline.com/consumers/oauth2/v2.0/token',
        )
        self.assertEqual(third_call.kwargs['data']['scope'], SCOPES)

    @patch('core.email_manager.requests.get')
    def test_reads_verification_code_from_graph_message(self, get):
        response = Mock(status_code=200, text='')
        response.json.return_value = {
            'value': [{
                'subject': 'Your Grok confirmation code',
                'from': {
                    'emailAddress': {
                        'name': 'xAI',
                        'address': 'no-reply@x.ai',
                    },
                },
                'receivedDateTime': datetime.now(timezone.utc).isoformat(),
                'bodyPreview': 'Use the code below to validate your email.',
                'body': {
                    'contentType': 'html',
                    'content': '<p>ABC-123 confirmation code</p>',
                },
            }],
        }
        get.return_value = response

        code = self.manager._graph_get_code('graph-access-token')

        self.assertEqual(code, 'ABC123')
        self.assertIn(
            'https://graph.microsoft.com/v1.0/me/messages',
            get.call_args.args[0],
        )
        self.assertNotIn('outlook.office.com', get.call_args.args[0])

    @patch('core.email_manager.requests.get')
    def test_graph_permission_denied_is_actionable(self, get):
        response = Mock(status_code=403, text='')
        response.json.return_value = {
            'error': {
                'code': 'ErrorAccessDenied',
                'message': 'Access is denied. Check credentials and try again.',
            },
        }
        get.return_value = response

        with self.assertRaisesRegex(
            EmailPermissionError,
            r'HTTP 403.*ErrorAccessDenied.*Access is denied',
        ):
            self.manager._graph_get_code('graph-access-token')

    @patch('core.email_manager.requests.get')
    def test_reads_verification_code_from_legacy_outlook_message(self, get):
        response = Mock(status_code=200, text='')
        response.json.return_value = {
            'value': [{
                'Subject': 'Your Grok confirmation code',
                'From': {
                    'EmailAddress': {
                        'Name': 'xAI',
                        'Address': 'no-reply@x.ai',
                    },
                },
                'ReceivedDateTime': datetime.now(timezone.utc).isoformat(),
                'BodyPreview': 'Use DEF-456 to confirm your email.',
                'Body': {'ContentType': 'Text', 'Content': 'DEF-456'},
            }],
        }
        get.return_value = response

        code = self.manager._outlook_get_code('opaque-outlook-token')

        self.assertEqual(code, 'DEF456')
        self.assertIn('outlook.office.com/api/v2.0', get.call_args.args[0])

    @patch('core.email_manager.requests.get')
    def test_detects_legacy_outlook_token_audience(self, get):
        graph_denied = Mock(status_code=401, text='')
        graph_denied.json.return_value = {
            'error': {'code': 'InvalidAuthenticationToken', 'message': 'invalid'},
        }
        outlook_allowed = Mock(status_code=200, text='')
        outlook_allowed.json.return_value = {'value': []}
        get.side_effect = [graph_denied, outlook_allowed]

        mail_api, error = self.manager._detect_mail_api('opaque-outlook-token')

        self.assertEqual(mail_api, 'outlook')
        self.assertEqual(error, '')
        self.assertEqual(get.call_count, 2)

    @patch('core.email_manager.time.sleep')
    def test_permission_error_is_not_retried(self, sleep):
        self.manager.refresh_token = Mock(
            return_value=('refresh-token', 'graph-access-token', 'graph'),
        )
        self.manager._graph_get_code = Mock(
            side_effect=EmailPermissionError(
                'Microsoft Graph mail failed: HTTP 403 (ErrorAccessDenied)'
            ),
        )

        with self.assertRaisesRegex(EmailPermissionError, 'HTTP 403'):
            self.manager.get_verification_code(
                'user+1@example.com',
                'client-id',
                'refresh-token',
                max_retries=3,
                account_id=9,
                main_email='user@example.com',
            )

        self.manager._graph_get_code.assert_called_once_with(
            'graph-access-token'
        )
        sleep.assert_called_once_with(8)


if __name__ == '__main__':
    unittest.main()
