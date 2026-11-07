"""HTTP client for the Polsat–Plus SSO and iPlus prepaid self-care."""
from __future__ import annotations

import json
import os
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Callable

import requests

DOMAINS = ('plus.pl', 'polsatbox.pl', 'polsat.pl', 'plusgsm.pl')
ACCOUNT = 'https://logowanie.plus.pl/usergui-backend/account/isLogged'
GOTO = 'https://logowanie.plus.pl/usergui/my-account'

class PlusError(RuntimeError):
    """A protocol or authentication error; never contains credentials."""

class AuthenticationError(PlusError):
    pass

class SMSRequired(PlusError):
    pass

class Forms(HTMLParser):
    """Extract forms and successful inputs without executing page JavaScript."""
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []
        self.inputs: dict[str, str] = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.forms.append({'action': a.get('action', ''), 'method': a.get('method', 'GET').upper(), 'fields': {}})
        if tag == 'input' and a.get('name') and 'disabled' not in a:
            if a.get('type', '').lower() in ('checkbox', 'radio') and 'checked' not in a:
                return
            self.inputs[a['name']] = a.get('value', '')
            if self.forms:
                self.forms[-1]['fields'][a['name']] = a.get('value', '')


def read_credentials(path: str | Path = '.env') -> tuple[str, str]:
    values = {}
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip() in ('user', 'pass'):
            values[key.strip()] = value.strip()
    if not values.get('user') or not values.get('pass'):
        raise PlusError('Credentials file must contain user: and pass: lines')
    return values['user'], values['pass']


class PlusSession(requests.Session):
    def send(self, request, **kwargs):
        p = urlparse(request.url)
        if p.scheme != 'https' or not any(p.hostname == d or (p.hostname or '').endswith('.' + d) for d in DOMAINS):
            raise PlusError('Refusing request outside the authorized Plus SSO domains')
        return super().send(request, **kwargs)


class PlusClient:
    def __init__(self, username: str, password: str, *, session_path: str | Path = 'session.json',
                 debug_dir: str | Path | None = None, timeout: float = 60, device_name: str = "Plus Balance",
                 max_password_submissions: int = 3, api_base: str = "https://webapi.plus.pl/api"):
        if not 1 <= max_password_submissions <= 3:
            raise ValueError("max_password_submissions must be between one and three")
        if not 1 <= len(device_name) <= 16:
            raise ValueError("device_name must contain one to sixteen characters")
        self.max_password_submissions = max_password_submissions
        self.device_name = device_name
        self.api_base = api_base.rstrip("/")
        self._secrets: set[str] = set()
        self.username, self._password = username, password
        self.session_path = Path(session_path)
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.timeout = timeout
        self.http = PlusSession()
        self.http.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        self.state = {'device_id': str(uuid.uuid4()), 'password_submissions': 0, 'login_failed': False}
        if self.session_path.exists():
            self.state.update(json.loads(self.session_path.read_text()))
            for cookie in self.state.get('cookies', []):
                self.http.cookies.set_cookie(requests.cookies.create_cookie(**cookie))
        self._save()
        self._dump_number = 0
        self._run_id = uuid.uuid4().hex[:8]
        self._login_url: str | None = self.state.get('login_url')

    def _save(self):
        self.state['cookies'] = [dict(name=c.name, value=c.value, domain=c.domain, path=c.path,
                                     secure=c.secure, expires=c.expires, rest=c._rest) for c in self.http.cookies]
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.session_path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(self.state, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.session_path)

    def _redact(self, text: str) -> str:
        secrets = [self._password, self.username, self.state.get('device_id', ''), *self._secrets]
        def collect(value, key=''):
            if isinstance(value, dict):
                for k, v in value.items(): collect(v, k)
            elif isinstance(value, list):
                for v in value: collect(v, key)
            elif isinstance(value, str) and (any(k in key.lower() for k in ('token', 'sessionid', 'subjectid', 'email', 'csrf', 'code')) or key == 'value'):
                if len(value) >= 4: secrets.append(value)
        collect(self.state)
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret: text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', text)
        text = re.sub(r'(?i)([\w.+-]+@[\w.-]+\.[a-z]{2,})', '[REDACTED]', text)
        text = re.sub(r'(?i)(name=["\'][^"\']+["\'][^>]*value=["\'])[^"\']*', r'\1[REDACTED]', text)
        text = re.sub(r'(?i)((?:delegateId|hazelcastId|stateId|RelayState)=)[^\s"\'<>&]+', r'\1[REDACTED]', text)
        text = re.sub(r'(?i)("(?:accessToken|refreshToken|csrfToken|idToken|sessionId|subjectId)"\s*:\s*")[^"]*', r'\1[REDACTED]', text)
        text = re.sub(r'\b\d{9,}\b', '[REDACTED]', text)
        return text

    def _request(self, method: str, url: str, **kwargs):
        try:
            r = self.http.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException:
            self._save()
            raise PlusError('Plus HTTP request failed; no automatic retry was made') from None
        self._save()
        if self.debug_dir:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            self._dump_number += 1
            r.encoding = 'utf-8'
            (self.debug_dir / f'{self._run_id}-{self._dump_number:03d}.txt').write_text(self._redact(r.text))
        return r

    def _follow_forms(self, r):
        for _ in range(12):
            forms = Forms(r.text).forms
            if not forms:
                return r
            form = forms[0]
            if not any(k in form['fields'] for k in ('SAMLRequest', 'SAMLResponse', 'hazelcastId', 'saml')):
                return r
            action = urljoin(r.url, form['action'])
            method = form['method']
            if 'ssopost' in action:
                action += ('&' if '?' in action else '?') + 'goto=' + GOTO
            r = self._request(method, action, **{('params' if method == 'GET' else 'data'): form['fields']})
            if r.status_code >= 400:
                raise PlusError(f'SSO form exchange failed (HTTP {r.status_code})')
        raise PlusError('Too many SSO form exchanges')

    def _step(self, fields: dict, *, expected_codes: tuple[str, ...] = ()):
        if not self._login_url:
            raise PlusError('No active authentication chain')
        if fields.get('otpCode'):
            self._secrets.add(fields['otpCode'])
        r = self._request('POST', self._login_url, data={'requestJson': json.dumps(fields)},
                          headers={'deviceId': self.state['device_id'], 'X-Requested-With': 'XMLHttpRequest'})
        try:
            result = r.json()
        except ValueError:
            raise AuthenticationError(f'Authentication returned unexpected content (HTTP {r.status_code})') from None
        code = str(result.get('code'))
        if code != '0' and code not in expected_codes:
            raise AuthenticationError(f'Authentication failed (HTTP {r.status_code}, code {code}); no retry made')
        if code == '0' and r.status_code >= 400:
            raise AuthenticationError(f'Authentication failed (HTTP {r.status_code}); no retry made')
        if result.get('loginUrl'):
            self._login_url = urljoin(self._login_url, result['loginUrl'])
        self.state['login_url'] = self._login_url
        self.state['pending_step'] = result
        self._save()
        return result

    def login(self, code_provider: Callable[[], str] | None = None):
        if self.state.get('pending_page') or self.state.get('pending_step'):
            return self._resume_login(code_provider)
        if self.state.get('login_failed'):
            raise AuthenticationError('A previous password submission failed; investigate before resetting login_failed in session.json')
        if self.state['password_submissions'] >= self.max_password_submissions:
            raise AuthenticationError('Password submission safety limit reached')
        r = self._follow_forms(self._request('GET', ACCOUNT))
        if 'userSearchAttributeValue' not in r.text:
            raise PlusError('Expected the Plus password form')
        match = re.search(r"loginFormActionPlaceHolder\s*=\s*['\"]([^'\"]+)", r.text)
        if not match:
            raise PlusError('Could not discover the authentication chain URL')
        self._login_url = match.group(1) + '&chainId=basic'
        fields = next(f['fields'] for f in Forms(r.text).forms if 'userSearchAttributeValue' in f['fields'])
        fields.update(userSearchAttributeValue=self.username, Pass=self._password)
        self.state['password_submissions'] += 1
        # A timeout after sending a password must never lead to an automatic retry.
        self.state['login_failed'] = True
        self._save()
        result = self._step(fields)
        self.state['login_failed'] = False
        self._save()
        return self._complete_login(result, code_provider)

    def _resume_login(self, code_provider):
        if self.state.get('pending_page'):
            return self._verify_device(code_provider)
        return self._complete_login(self.state['pending_step'], code_provider)

    def _verify_device(self, code_provider):
        page = self.state['pending_page']
        forms = Forms(page['html']).forms
        if not self.state.get('sms_requested'):
            form = next((f for f in forms if 'readyToBeProcessed' in f['fields'] and 'otpCode' not in f['fields']), None)
            if not form:
                raise PlusError('Unrecognized trusted-device selection form')
            fields = dict(form['fields'])
            fields.update(readyToBeProcessed='true', userAccessTrustedDeviceAttributeName='saveDeviceTrustedDeviceAttributeName')
            self._step(fields, expected_codes=('533',))
            self.state['sms_requested'] = True
            self._save()
        result = self.state.get('pending_step', {})
        if str(result.get('code')) not in ('608', '609'):
            if code_provider is None:
                raise SMSRequired('SMS code required; call login(code_provider=...) to resume the saved chain')
            code = code_provider().strip()
            if not re.fullmatch(r'\d{4}', code):
                raise PlusError('The Plus SMS code must contain four digits')
            form = next((f for f in forms if 'otpCode' in f['fields'] and 'readyToBeProcessed' in f['fields']), None)
            if not form:
                raise PlusError('Unrecognized SMS verification form')
            fields = dict(form['fields'])
            fields.update(otpCode=code, readyToBeProcessed='true',
                          userAccessTrustedDeviceAttributeName='saveDeviceTrustedDeviceAttributeName',
                          trustedDeviceName=self.device_name)
            result = self._step(fields, expected_codes=('608', '609'))
            # Keep the code only until the website's "Rozumiem" confirmation is complete.
            self.state['pending_otp'] = code
            self._save()
        if str(result.get('code')) in ('608', '609'):
            code = self.state.get('pending_otp')
            if not code:
                raise SMSRequired('Resume device confirmation with the original SMS code')
            result = self._step({'isModalConfirmed': 'true', 'otpCode': code})
            self.state['trusted_device'] = True
            self.state.pop('pending_page', None)
            self.state.pop('pending_otp', None)
            self._save()
        return self._complete_login(result, code_provider)

    def _complete_login(self, result, code_provider):
        for _ in range(8):
            html = result.get('nextStepForm', '')
            if html and 'auto-submit="true"' in html:
                result = self._step(Forms(html).inputs)
                continue
            if html:
                raise PlusError('Unrecognized nonautomatic authentication step; saved in session.json')
            if result.get('redirectBody'):
                from types import SimpleNamespace
                response = self._follow_forms(SimpleNamespace(text=result['redirectBody'], url=self._login_url))
            elif result.get('redirectUrl'):
                response = self._follow_forms(self._request('GET', urljoin(self._login_url, result['redirectUrl'])))
            else:
                raise PlusError('Unrecognized authentication result')
            if '/sso/login/otp/page' in response.url:
                self.state['pending_page'] = {'url': response.url, 'html': response.text}
                self.state['sms_requested'] = False
                self._save()
                return self._verify_device(code_provider)
            if 'userSearchAttributeValue' in response.text and 'name="Pass"' in response.text:
                raise AuthenticationError('SSO returned to the password form; no retry made')
            for key in ('pending_step', 'pending_page', 'pending_otp', 'sms_requested'):
                self.state.pop(key, None)
            self._save()
            r = self._request('GET', ACCOUNT)
            if not self._account_authenticated(r):
                raise AuthenticationError('SSO completion could not be verified; no retry made')
            # The safety counter limits consecutive unverified attempts, not lifetime logins.
            self.state['password_submissions'] = 0
            self._save()
            return
        raise PlusError('Too many authentication steps')

    def reset_login_lock(self):
        """Allow a new password attempt after the user re-entered credentials."""
        self.state['login_failed'] = False
        self.state['password_submissions'] = 0
        self._save()

    @staticmethod
    def _account_authenticated(response):
        try:
            return response.status_code == 200 and response.json() == {'message': 'PLK'}
        except ValueError:
            return False

    def ensure_session(self, code_provider: Callable[[], str] | None = None):
        """Reuse cookies, resume pending SMS, or submit a password once if necessary."""
        if self.state.get('pending_page') or self.state.get('pending_step'):
            self._resume_login(code_provider)
        elif not self._account_authenticated(self._request('GET', ACCOUNT)):
            # isLogged answers with a SAML form when only the usergui session expired;
            # replaying it against a still-valid SSO session avoids a password login.
            self._follow_forms(self._request('GET', ACCOUNT))
            if not self._account_authenticated(self._request('GET', ACCOUNT)):
                self.login(code_provider)
        return self._ensure_iplus()

    def _ensure_iplus(self, *, force=False):
        """Use the iPlus NextAuth cookie or exchange the existing SSO session."""
        root = 'https://iplus.plus.pl'
        self.http.cookies.set('device_id', self.state['device_id'], domain='iplus.plus.pl', path='/', secure=True)
        r = self._request('GET', root + '/api/auth/session')
        session = self._json(r)
        import time
        if force or not session.get('accessToken') or session.get('expires_at', 0) <= time.time() + 30:
            csrf = self._json(self._request('GET', root + '/api/auth/csrf')).get('csrfToken')
            if not csrf:
                raise PlusError('iPlus did not provide a CSRF token')
            self._secrets.add(csrf)
            result = self._json(self._request('POST', root + '/api/auth/signin/iplus',
                                params={'device_id': self.state['device_id']},
                                data={'csrfToken': csrf, 'callbackUrl': root + '/', 'json': 'true'},
                                headers={'X-Auth-Return-Redirect': '1'}))
            if not result.get('url'):
                raise PlusError('iPlus did not provide its authorization URL')
            response = self._follow_forms(self._request('GET', result['url']))
            if 'name="Pass"' in response.text:
                raise AuthenticationError('iPlus SSO needs reauthentication; no password retry made')
            session = self._json(self._request('GET', root + '/api/auth/session'))
        if not session.get('accessToken'):
            raise AuthenticationError('iPlus did not establish an authenticated session')
        self.state['iplus_session'] = session
        self._save()
        return session

    @staticmethod
    def _json(response):
        try:
            value = response.json()
        except ValueError:
            raise PlusError(f'Expected JSON from Plus (HTTP {response.status_code})') from None
        if not isinstance(value, dict):
            raise PlusError('Expected a JSON object from Plus')
        return value

    def _api_get(self, path):
        from datetime import datetime, timezone
        session = self.state.get('iplus_session') or self.ensure_session()
        for attempt in range(2):
            r = self._request('GET', self.api_base + path, headers={
                'Authorization': 'Bearer ' + session['accessToken'],
                'Device-Id': self.state['device_id'], 'X-Channel': 'web', 'appId': 'iplus',
                'date': datetime.now(timezone.utc).isoformat(), 'traceId': str(uuid.uuid4()),
                'Accept': 'application/json', 'Origin': 'https://iplus.plus.pl',
                'Referer': 'https://iplus.plus.pl/',
            })
            if r.status_code in (401, 403) and attempt == 0:
                session = self._ensure_iplus(force=True)
                continue
            if r.status_code >= 400:
                raise PlusError(f'Plus data API failed (HTTP {r.status_code})')
            return self._json(r)

    def get_balance(self, msisdn: str | None = None):
        """Read active prepaid data usages for each authorized subscription."""
        from urllib.parse import quote
        from .parser import parse_products, summarize_packages
        self.ensure_session()
        linked = self._api_get('/v1/sso/authorized-accounts')
        selected = re.sub(r'\D', '', msisdn) if msisdn else None
        if selected and len(selected) == 9:
            selected = '48' + selected
        numbers = []
        for account in linked.get('accounts', []):
            if account.get('type') != 'Prepaid' or not account.get('isAuthorized'):
                continue
            for subscription in account.get('subscriptions', []):
                number = str(subscription.get('msisdn', ''))
                if re.fullmatch(r'48\d{9}', number) and (selected is None or selected == number):
                    if number not in numbers:
                        numbers.append(number)
        if not numbers:
            raise PlusError('No matching authorized prepaid subscription was found')
        balances = []
        for number in numbers:
            payload = self._api_get('/v1/subscription/' + quote(number, safe='') + '/products?productType=data')
            packages = parse_products(payload)
            summary = summarize_packages(packages)
            for package in packages:
                date = package['valid_until']
                package['valid_until'] = date.isoformat() if date else None
            date = summary['valid_until']
            summary['valid_until'] = date.isoformat() if date else None
            balances.append({'msisdn': number, 'packages': packages, **summary})
        return {'subscriptions': balances}

    def close(self):
        self._save()
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
