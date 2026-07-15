import os
import tempfile
import unittest
from unittest.mock import patch

import core.database as database_module
from core.database import Database, DEFAULT_SETTINGS


class MaxAliasesSettingTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_patch = patch.object(
            database_module,
            'DB_PATH',
            os.path.join(self.temp_dir.name, 'test.db'),
        )
        self.db_path_patch.start()
        self.previous_instance = Database._instance
        Database._instance = None
        self.db = Database()
        self.db.init_database()

    def tearDown(self):
        self.db.conn.close()
        Database._instance = self.previous_instance
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def _insert_used_aliases(self, account_id, count):
        for index in range(count):
            self.db.conn.execute(
                '''INSERT INTO aliases (
                       account_id, alias_email, alias_index, status
                   ) VALUES (?, ?, ?, 'used')''',
                (account_id, f'main+{index}@example.com', index),
            )
        self.db.conn.commit()

    def test_new_account_uses_current_max_aliases_setting(self):
        self.db.update_settings({'max_aliases_per_account': '10'})

        account_id = self.db.upsert_account(
            'main@example.com', '', 'client-id', 'refresh-token'
        )

        account = self.db.get_account(account_id)
        self.assertEqual(account['max_aliases'], 10)

    def test_setting_change_updates_limit_and_recomputes_account_status(self):
        account_id = self.db.upsert_account(
            'main@example.com', '', 'client-id', 'refresh-token'
        )
        self._insert_used_aliases(account_id, 5)
        self.db.update_account_status(account_id, 'done')

        self.db.update_settings({'max_aliases_per_account': '10'})

        account = self.db.get_account(account_id)
        self.assertEqual(account['max_aliases'], 10)
        self.assertEqual(account['status'], 'ready')

        self.db.update_settings({'max_aliases_per_account': '4'})

        account = self.db.get_account(account_id)
        self.assertEqual(account['max_aliases'], 4)
        self.assertEqual(account['status'], 'done')

    def test_setting_change_preserves_disabled_status(self):
        account_id = self.db.upsert_account(
            'main@example.com', '', 'client-id', 'refresh-token'
        )
        self.db.update_account_status(account_id, 'disabled')

        self.db.update_settings({'max_aliases_per_account': '10'})

        account = self.db.get_account(account_id)
        self.assertEqual(account['max_aliases'], 10)
        self.assertEqual(account['status'], 'disabled')

    def test_startup_reconciles_accounts_from_existing_global_setting(self):
        account_id = self.db.upsert_account(
            'main@example.com', '', 'client-id', 'refresh-token'
        )
        self._insert_used_aliases(account_id, 5)
        self.db.update_account_status(account_id, 'done')
        self.db.conn.execute(
            "UPDATE settings SET value='10' WHERE key='max_aliases_per_account'"
        )
        self.db.conn.commit()
        self.db.conn.close()

        Database._instance = None
        self.db = Database()
        self.db.init_database()

        account = self.db.get_account(account_id)
        self.assertEqual(account['max_aliases'], 10)
        self.assertEqual(account['status'], 'ready')

    def test_reset_restores_default_limit_and_status(self):
        self.db.update_settings({'max_aliases_per_account': '10'})
        account_id = self.db.upsert_account(
            'main@example.com', '', 'client-id', 'refresh-token'
        )
        self._insert_used_aliases(account_id, 5)

        self.db.reset_settings()

        account = self.db.get_account(account_id)
        self.assertEqual(
            account['max_aliases'],
            int(DEFAULT_SETTINGS['max_aliases_per_account']),
        )
        self.assertEqual(account['status'], 'done')

    def test_invalid_max_aliases_setting_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            self.db.update_settings({'max_aliases_per_account': '0'})

        self.assertEqual(
            self.db.get_settings()['max_aliases_per_account'],
            DEFAULT_SETTINGS['max_aliases_per_account'],
        )


if __name__ == '__main__':
    unittest.main()
