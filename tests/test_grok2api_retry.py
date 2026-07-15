import unittest
from unittest.mock import Mock, patch

from core.grok2api_retry import Grok2APIRetryWorker


class Grok2APIRetryWorkerTest(unittest.TestCase):
    def test_retries_claimed_delivery_and_marks_success(self):
        db = Mock()
        db.get_settings.return_value = {
            'grok2api_auto_upload': 'true',
            'grok2api_url': 'http://127.0.0.1:21434',
        }
        db.claim_grok2api_retries.return_value = [{
            'id': 9,
            'email': 'user@example.com',
            'sso_value': 'sso-token',
        }]
        worker = Grok2APIRetryWorker(db)

        with patch('core.grok2api_retry.upload_registered_sso') as upload:
            self.assertEqual(worker.run_once(), 1)

        upload.assert_called_once_with(
            db.get_settings.return_value,
            'sso-token',
            email='user@example.com',
        )
        db.finish_grok2api_upload.assert_called_once_with(9, True)

    def test_failed_delivery_is_kept_for_later_retry(self):
        db = Mock()
        db.get_settings.return_value = {'grok2api_auto_upload': 'true'}
        db.claim_grok2api_retries.return_value = [{
            'id': 10,
            'email': 'user@example.com',
            'sso_value': 'sso-token',
        }]
        worker = Grok2APIRetryWorker(db)

        with patch(
            'core.grok2api_retry.upload_registered_sso',
            side_effect=RuntimeError('temporary'),
        ):
            self.assertEqual(worker.run_once(), 0)

        db.finish_grok2api_upload.assert_called_once()
        self.assertFalse(db.finish_grok2api_upload.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
