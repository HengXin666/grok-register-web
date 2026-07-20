import unittest

from core.grok2api_client import Grok2APIChatPermissionError, Grok2APIError
from core.registration.state import RegistrationState


class ChatProbeStatsTest(unittest.TestCase):
    def test_snapshot_includes_probe_counters(self):
        state = RegistrationState()
        snap = state.get_snapshot()
        self.assertEqual(snap['chat_probe_passed'], 0)
        self.assertEqual(snap['chat_probe_denied'], 0)
        self.assertEqual(snap['chat_probe_failed'], 0)
        self.assertEqual(snap['chat_probe_skipped'], 0)

    def test_record_from_upload_result_shapes(self):
        state = RegistrationState()
        state.record_chat_probe_from_upload({
            'grok2api': {'probe': {'ok': True, 'status': 200}},
        }, reg_id=1)
        state.record_chat_probe_from_upload({
            'grok2api': {'probe': {'ok': True, 'skipped': True}},
        }, reg_id=2)
        state.record_chat_probe_from_upload({
            'grok2api_probe_denied': {'status': 403, 'error': 'Access denied.'},
        }, reg_id=3)
        state.record_chat_probe_from_upload({
            'grok2api': {'probe': {'ok': False, 'status': 429, 'error': 'rate'}},
        }, reg_id=4)

        snap = state.get_snapshot()
        self.assertEqual(snap['chat_probe_passed'], 1)
        self.assertEqual(snap['chat_probe_skipped'], 1)
        self.assertEqual(snap['chat_probe_denied'], 1)
        self.assertEqual(snap['chat_probe_failed'], 1)

    def test_record_from_permission_error(self):
        state = RegistrationState()
        state.record_chat_probe_from_upload(
            error=Grok2APIChatPermissionError({'status': 403, 'error': 'Access denied.'}),
            reg_id=11,
        )
        self.assertEqual(state.get_snapshot()['chat_probe_denied'], 1)

    def test_record_from_probe_runtime_error(self):
        state = RegistrationState()
        state.record_chat_probe_from_upload(
            error=RuntimeError('grok2api chat probe failed: HTTP 429: rate'),
            reg_id=12,
        )
        self.assertEqual(state.get_snapshot()['chat_probe_failed'], 1)

    def test_mint_rate_limit_counts_as_failed(self):
        """device/code 429 must not silently drop from dashboard tiles."""
        state = RegistrationState()
        state.record_chat_probe_from_upload(
            error=Grok2APIError(
                'https://auth.x.ai/oauth2/device/code returned HTTP 429: '
                '{"error":"slow_down"}'
            ),
            reg_id=20,
        )
        snap = state.get_snapshot()
        self.assertEqual(snap['chat_probe_failed'], 1)
        self.assertEqual(snap['chat_probe_passed'], 0)
        self.assertEqual(snap['chat_probe_denied'], 0)

    def test_build_failure_after_probe_counts_as_passed(self):
        """Probe already ok when Build conversion fails → still chat-passed."""
        state = RegistrationState()
        err = Grok2APIError('grok2api Build conversion failed for Web account 3962')
        err.probe = {'ok': True, 'status': 200, 'model': 'grok-4.5-build-free'}
        state.record_chat_probe_from_upload(error=err, reg_id=21)
        self.assertEqual(state.get_snapshot()['chat_probe_passed'], 1)
        self.assertEqual(state.get_snapshot()['chat_probe_failed'], 0)

    def test_durable_retry_upgrades_failed_to_passed(self):
        state = RegistrationState()
        state.record_chat_probe_from_upload(
            error=Grok2APIError('device/code 429 slow_down'),
            reg_id=30,
        )
        self.assertEqual(state.get_snapshot()['chat_probe_failed'], 1)

        state.record_chat_probe_from_upload(
            {
                'grok2api': {
                    'probe': {'ok': True, 'status': 200},
                    'import': {'created': 1},
                    'conversion': {'created': 1},
                },
            },
            reg_id=30,
        )
        snap = state.get_snapshot()
        self.assertEqual(snap['chat_probe_failed'], 0)
        self.assertEqual(snap['chat_probe_passed'], 1)
        self.assertEqual(snap['chat_probe_denied'], 0)

    def test_durable_retry_upgrades_failed_to_denied(self):
        state = RegistrationState()
        state.record_chat_probe_from_upload(
            error=Grok2APIError('device/code 429 slow_down'),
            reg_id=31,
        )
        state.record_chat_probe_from_upload(
            error=Grok2APIChatPermissionError({
                'status': 403,
                'error': 'Access to the chat endpoint is denied.',
            }),
            reg_id=31,
        )
        snap = state.get_snapshot()
        self.assertEqual(snap['chat_probe_failed'], 0)
        self.assertEqual(snap['chat_probe_denied'], 1)
        self.assertEqual(snap['chat_probe_passed'], 0)

    def test_duplicate_same_outcome_is_idempotent(self):
        state = RegistrationState()
        result = {'grok2api': {'probe': {'ok': True, 'status': 200}}}
        state.record_chat_probe_from_upload(result, reg_id=40)
        state.record_chat_probe_from_upload(result, reg_id=40)
        self.assertEqual(state.get_snapshot()['chat_probe_passed'], 1)


if __name__ == '__main__':
    unittest.main()
