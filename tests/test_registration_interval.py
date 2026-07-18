import threading
import time
import unittest

from core.registration.state import RegistrationState


class RegistrationIntervalTests(unittest.TestCase):
    def test_interval_wait_updates_snapshot_and_finishes(self):
        state = RegistrationState()
        state.status = 'running'

        self.assertTrue(state.wait_for_next_round(0.02))

        snapshot = state.get_snapshot()
        self.assertEqual(snapshot['status'], 'running')
        self.assertEqual(snapshot['next_round_in'], 0)
        self.assertIsNone(snapshot['next_round_at'])

    def test_interval_wait_can_be_stopped(self):
        state = RegistrationState()
        state.status = 'running'
        result = []
        thread = threading.Thread(
            target=lambda: result.append(state.wait_for_next_round(5)),
        )
        thread.start()

        deadline = time.time() + 1
        while state.get_snapshot()['status'] != 'waiting' and time.time() < deadline:
            time.sleep(0.005)
        state.stop()
        thread.join(timeout=1.5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(state.get_snapshot()['next_round_in'], 0)


if __name__ == '__main__':
    unittest.main()
