import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from plus_balance.client import PlusClient, PlusError


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload, text='', url='https://iplus.plus.pl/')


@pytest.fixture
def client(tmp_path):
    client = PlusClient('example', 'secret', session_path=tmp_path / 'session.json')
    yield client
    client.close()


def test_cookie_precedes_signin_and_preserves_trust(client):
    client.http.cookies.set('prst-cookie', 'trusted', domain='logowanie.plus.pl', path='/')
    def request(method, url, **kwargs):
        if '/signin/' in url:
            assert client.http.cookies.get('device_id', domain='iplus.plus.pl', path='/') == client.state['device_id']
            return response({'url': 'https://iplus.plus.pl/authorize'})
        if url.endswith('/csrf'):
            return response({'csrfToken': 'csrf'})
        return response({'accessToken': 'new', 'expires_at': 9999999999})
    client._request = Mock(side_effect=request)
    client._ensure_iplus(force=True)
    assert client.http.cookies.get('prst-cookie') == 'trusted'
    assert any('/signin/' in call.args[1] for call in client._request.call_args_list)


@pytest.mark.parametrize('status', [401, 403])
def test_single_refresh(client, status):
    client.state['iplus_session'] = {'accessToken': 'old'}
    client._request = Mock(side_effect=[response({}, status), response({'ok': True})])
    client._ensure_iplus = Mock(return_value={'accessToken': 'new'})
    assert client._api_get('/test') == {'ok': True}
    client._ensure_iplus.assert_called_once_with(force=True)
    assert client._request.call_args.kwargs['headers']['Authorization'] == 'Bearer new'


def test_retry_denied_is_error(client):
    client.state['iplus_session'] = {'accessToken': 'old'}
    client._request = Mock(return_value=response({}, 403))
    client._ensure_iplus = Mock(return_value={'accessToken': 'new'})
    with pytest.raises(PlusError, match='403'):
        client._api_get('/test')
    assert client._request.call_count == 2


def test_products_per_selected_subscription(client):
    client.ensure_session = Mock()
    fixture = json.loads((Path(__file__).parent / 'fixtures/products_data.json').read_text())
    client._api_get = Mock(side_effect=[{'accounts': [
        {'type': 'Prepaid', 'isAuthorized': True, 'subscriptions': [{'msisdn': '48000000000'}, {'msisdn': '48000000001'}]},
        {'type': 'Postpaid', 'isAuthorized': True, 'subscriptions': [{'msisdn': '48000000002'}]},
    ]}, fixture])
    result = client.get_balance('000000001')
    assert client._api_get.call_args.args == ('/v1/subscription/48000000001/products?productType=data',)
    subscription, = result['subscriptions']
    assert subscription['msisdn'] == '48000000001'
    assert subscription['total_remaining_gb'] == 8.49
    assert subscription['valid_until'] == '2026-12-07T09:33:48+00:00'
    json.dumps(result)


def test_reset_login_lock_clears_failure_and_counter(tmp_path):
    from plus_balance.client import PlusClient
    client = PlusClient('user@example.com', 'secret', session_path=tmp_path / 's.json')
    client.state.update(login_failed=True, password_submissions=3)
    client.reset_login_lock()
    reloaded = PlusClient('user@example.com', 'secret', session_path=tmp_path / 's.json')
    assert reloaded.state['login_failed'] is False
    assert reloaded.state['password_submissions'] == 0
