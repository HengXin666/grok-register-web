"""Durable background delivery for successful registrations."""

import logging
import threading

from core.grok2api_client import Grok2APIChatPermissionError, upload_registered_sso


logger = logging.getLogger('register')


class Grok2APIRetryWorker:
    def __init__(self, db, interval_seconds=60):
        self.db = db
        self.interval_seconds = max(10, int(interval_seconds))
        self._stop = threading.Event()
        self._thread = None

    def run_once(self):
        settings = self.db.get_settings()
        if settings.get('grok2api_auto_upload', 'false') != 'true':
            return 0
        records = self.db.claim_grok2api_retries(limit=20)
        completed = 0
        for record in records:
            try:
                result = upload_registered_sso(
                    settings,
                    record['sso_value'],
                    email=record['email'],
                )
            except Exception as exc:
                if isinstance(exc, Grok2APIChatPermissionError):
                    self.db.finish_grok2api_probe(record['id'], exc.probe)
                else:
                    self.db.finish_grok2api_upload(record['id'], False, exc)
                logger.warning(
                    'grok2api durable retry failed: registration_id=%s error=%s',
                    record['id'], exc,
                )
            else:
                if isinstance(result, dict) and result.get('grok2api_probe_denied'):
                    self.db.finish_grok2api_probe(
                        record['id'], result['grok2api_probe_denied'],
                    )
                else:
                    self.db.finish_grok2api_upload(record['id'], True)
                    completed += 1
                    logger.info(
                        'grok2api durable retry completed: registration_id=%s',
                        record['id'],
                    )
        return completed

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name='grok2api-delivery-retry',
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.warning('grok2api durable retry worker failed: %s', exc)
            self._stop.wait(self.interval_seconds)
