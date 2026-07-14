import logging
import re
import time

import requests

from config import SCOPES, TOKEN_URL


logger = logging.getLogger('register')


class EmailError(Exception):
    pass


class EmailPermissionError(EmailError):
    """The mailbox token cannot read mail and retrying will not help."""


class EmailManager:
    def __init__(self, db):
        self.db = db

    def refresh_token(self, account_id, client_id, old_refresh_token):
        """Refresh a mail token and match it to its authorized API audience."""
        endpoints = [
            # Legacy imported tokens commonly issue opaque Outlook REST tokens
            # only when no scope override is supplied.
            (TOKEN_URL, {}),
            ('https://login.microsoftonline.com/consumers/oauth2/v2.0/token', {}),
            # Newly authorized accounts use Microsoft Graph Mail.Read.
            (
                'https://login.microsoftonline.com/consumers/oauth2/v2.0/token',
                {'scope': SCOPES},
            ),
            (TOKEN_URL, {'scope': SCOPES}),
        ]
        errors = []
        for url, extra in endpoints:
            try:
                data = {
                    'client_id': client_id,
                    'refresh_token': old_refresh_token,
                    'grant_type': 'refresh_token',
                    **extra,
                }
                response = requests.post(url, data=data, timeout=30)
                try:
                    token_data = response.json()
                except ValueError:
                    token_data = {}
                logger.info(
                    'Token endpoint: status=%s, has_access_token=%s, error=%s',
                    response.status_code,
                    bool(token_data.get('access_token')),
                    token_data.get('error', 'none'),
                )
                access_token = token_data.get('access_token')
                if access_token:
                    new_token = token_data.get('refresh_token', old_refresh_token)
                    self.db.update_refresh_token(account_id, new_token)
                    old_refresh_token = new_token
                    mail_api, probe_error = self._detect_mail_api(access_token)
                    if mail_api:
                        logger.info(
                            'Mailbox token refreshed OK: api=%s, token_len=%s',
                            mail_api,
                            len(access_token),
                        )
                        return new_token, access_token, mail_api
                    errors.append(probe_error)
                    continue

                description = str(
                    token_data.get('error_description')
                    or token_data.get('error')
                    or response.text
                    or 'no access token'
                ).strip()
                errors.append(f'HTTP {response.status_code}: {description[:160]}')
            except Exception as exc:
                errors.append(str(exc)[:160])
                logger.warning('Token endpoint failed: %s', exc)

        detail = ' | '.join(errors)
        raise EmailPermissionError(
            f'Microsoft mailbox token refresh failed or access check failed'
            f'{f": {detail}" if detail else ""}'
        )

    def get_verification_code(self, email_addr, client_id, refresh_token,
                              max_retries=3, account_id=None, main_email=None):
        """Poll the token's mail API for the verification mail sent to an alias."""
        # The OAuth token belongs to the main mailbox; plus-address aliases are
        # delivered to that same mailbox, so no provider/address switch is needed.
        _, access_token, mail_api = self.refresh_token(
            account_id or 0, client_id, refresh_token,
        )

        # Give xAI a moment to deliver the email before the first poll.
        time.sleep(8)

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    'Fetching verification code for %s via %s... (attempt %s/%s)',
                    email_addr,
                    mail_api,
                    attempt,
                    max_retries,
                )
                if mail_api == 'graph':
                    code = self._graph_get_code(access_token)
                else:
                    code = self._outlook_get_code(access_token)
                if code:
                    logger.info(
                        'Verification code obtained (%s): %s',
                        mail_api,
                        code,
                    )
                    return code
            except EmailPermissionError:
                # Repeating the same request or switching aliases cannot make
                # an unreadable token gain mail access.
                raise
            except EmailError as exc:
                last_error = exc
                logger.warning('%s mail attempt %s failed: %s', mail_api, attempt, exc)

            if attempt < max_retries:
                time.sleep(5)

        if last_error:
            raise EmailError(
                f'Failed to get verification code after {max_retries} attempts; '
                f'last mail error: {last_error}'
            )
        raise EmailError(
            f'Failed to get verification code after {max_retries} attempts'
        )

    def _detect_mail_api(self, access_token):
        """Return the mail API authorized for an imported access token."""
        probes = (
            (
                'graph',
                'https://graph.microsoft.com/v1.0/me/messages?$top=1&$select=id',
            ),
            (
                'outlook',
                'https://outlook.office.com/api/v2.0/me/messages?$top=1&$select=Id',
            ),
        )
        errors = []
        for name, url in probes:
            try:
                response = requests.get(
                    url,
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'Accept': 'application/json',
                    },
                    timeout=30,
                )
            except Exception as exc:
                errors.append(f'{name} probe: {exc}')
                continue
            if response.status_code == 200:
                return name, ''
            code, message = self._mail_api_error(response)
            detail = ': '.join(part for part in (code, message) if part)
            errors.append(
                f'{name} probe HTTP {response.status_code}'
                f'{f" ({detail})" if detail else ""}'
            )
        return None, '; '.join(errors)

    def _graph_get_code(self, access_token):
        """Fetch recent verification messages through Microsoft Graph."""
        from datetime import datetime, timedelta, timezone
        import html as html_module

        logger.info('Graph _graph_get_code: token_len=%s', len(access_token))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        url = (
            'https://graph.microsoft.com/v1.0/me/messages'
            '?$top=25'
            '&$select=subject,from,receivedDateTime,bodyPreview,body'
            '&$orderby=receivedDateTime desc'
        )
        response = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
            },
            timeout=30,
        )
        if response.status_code != 200:
            code, message = self._mail_api_error(response)
            detail = ': '.join(part for part in (code, message) if part)
            error = (
                f'Microsoft Graph mail failed: HTTP {response.status_code}'
                f'{f" ({detail})" if detail else ""}'
            )
            if response.status_code in (401, 403):
                raise EmailPermissionError(error)
            raise EmailError(error)

        try:
            messages = response.json().get('value', [])
        except (AttributeError, ValueError) as exc:
            raise EmailError(f'Microsoft Graph returned invalid JSON: {exc}') from exc

        keywords = (
            'x.ai', 'xai', 'grok', 'verification',
            'code', 'confirm', 'confirmation',
        )
        for message in messages:
            received = message.get('receivedDateTime') or ''
            try:
                received_at = datetime.fromisoformat(
                    received.replace('Z', '+00:00')
                )
                if received_at < cutoff:
                    continue
            except (TypeError, ValueError):
                pass

            subject = message.get('subject') or ''
            sender_data = message.get('from') or {}
            email_address = (
                sender_data.get('emailAddress') or {}
                if isinstance(sender_data, dict) else {}
            )
            sender = (
                f"{email_address.get('name', '')} "
                f"{email_address.get('address', '')}"
            )
            preview = message.get('bodyPreview') or ''
            body_data = message.get('body') or {}
            if not isinstance(body_data, dict):
                body_data = {}
            raw_body = body_data.get('content') or ''
            if (body_data.get('contentType') or '').upper() == 'HTML':
                body = re.sub(
                    r'\s+',
                    ' ',
                    re.sub(
                        r'<[^>]+>',
                        ' ',
                        html_module.unescape(raw_body),
                    ),
                ).strip()
            else:
                body = raw_body

            combined = f'{subject} {sender} {preview} {body}'.lower()
            if not any(keyword in combined for keyword in keywords):
                continue

            code = self._extract_code_from_email(
                f'{subject}\n{preview}\n{body}'
            )
            if code:
                return code

        logger.debug('No verification code found via Microsoft Graph')
        return None

    def _outlook_get_code(self, access_token):
        """Fetch mail for legacy opaque tokens authorized for Outlook REST."""
        from datetime import datetime, timedelta, timezone
        import html as html_module

        logger.info('Outlook _outlook_get_code: token_len=%s', len(access_token))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        url = (
            'https://outlook.office.com/api/v2.0/me/messages'
            '?$top=25'
            '&$select=Subject,From,ReceivedDateTime,BodyPreview,Body'
            '&$orderby=ReceivedDateTime desc'
        )
        response = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
            },
            timeout=30,
        )
        if response.status_code != 200:
            code, message = self._mail_api_error(response)
            detail = ': '.join(part for part in (code, message) if part)
            error = (
                f'Outlook REST mail failed: HTTP {response.status_code}'
                f'{f" ({detail})" if detail else ""}'
            )
            if response.status_code in (401, 403):
                raise EmailPermissionError(error)
            raise EmailError(error)

        try:
            messages = response.json().get('value', [])
        except (AttributeError, ValueError) as exc:
            raise EmailError(f'Outlook REST returned invalid JSON: {exc}') from exc

        keywords = (
            'x.ai', 'xai', 'grok', 'verification',
            'code', 'confirm', 'confirmation',
        )
        for message in messages:
            received = message.get('ReceivedDateTime') or ''
            try:
                received_at = datetime.fromisoformat(
                    received.replace('Z', '+00:00')
                )
                if received_at < cutoff:
                    continue
            except (TypeError, ValueError):
                pass

            subject = message.get('Subject') or ''
            sender_data = message.get('From') or {}
            email_address = (
                sender_data.get('EmailAddress') or {}
                if isinstance(sender_data, dict) else {}
            )
            sender = (
                f"{email_address.get('Name', '')} "
                f"{email_address.get('Address', '')}"
            )
            preview = message.get('BodyPreview') or ''
            body_data = message.get('Body') or {}
            if not isinstance(body_data, dict):
                body_data = {}
            raw_body = body_data.get('Content') or ''
            if (body_data.get('ContentType') or '').upper() == 'HTML':
                body = re.sub(
                    r'\s+',
                    ' ',
                    re.sub(
                        r'<[^>]+>',
                        ' ',
                        html_module.unescape(raw_body),
                    ),
                ).strip()
            else:
                body = raw_body

            combined = f'{subject} {sender} {preview} {body}'.lower()
            if not any(keyword in combined for keyword in keywords):
                continue
            code = self._extract_code_from_email(
                f'{subject}\n{preview}\n{body}'
            )
            if code:
                return code

        logger.debug('No verification code found via Outlook REST')
        return None

    @staticmethod
    def _mail_api_error(response):
        try:
            error = response.json().get('error') or {}
        except (AttributeError, ValueError):
            error = {}
        code = str(error.get('code') or '').strip()
        message = str(error.get('message') or '').strip()
        if not code and not message:
            message = str(getattr(response, 'text', '') or '')[:200].strip()
        return code, message

    def _extract_code_from_email(self, body):
        """Extract the xAI verification code from a message body."""
        match = re.search(
            r'\b([A-Z0-9]{3}-[A-Z0-9]{3})\b.*confirmation\s*code',
            body or '',
            re.IGNORECASE,
        )
        if match:
            return match.group(1).upper().replace('-', '')

        patterns = [
            r'code\s+below\s+to\s+validate.*?\n\s*([A-Z0-9]{3}-[A-Z0-9]{3})\s*\n',
            r'\b([A-Z0-9]{3}-[A-Z0-9]{3})\b',
            r'(?:verification\s*code|code\s+)[:\s]+(\d{6})',
            r'(?:验证码|代码|确认码)[:\s为]+(\d{6})',
            r'(?:code|验证码)[:\s]+(\d{6})',
            r'\b(\d{6})\b',
            r'\b([A-Z0-9]{6})\b',
        ]
        for pattern in patterns:
            match = re.search(pattern, body or '', re.IGNORECASE | re.DOTALL)
            if match:
                code = match.group(1)
                return code.upper().replace('-', '') if '-' in code else code.upper()
        return None

    def get_code_for_alias(self, alias_email, account_id, client_id,
                           refresh_token, max_retries=3, main_email=None):
        """Fetch the code for the mailbox address already submitted to xAI.

        After the signup form has been filled with ``alias_email``, switching
        to another provider cannot receive the code and only burns rate limits.
        """
        return self.get_verification_code(
            alias_email,
            client_id,
            refresh_token,
            max_retries,
            account_id=account_id,
            main_email=main_email,
        )
