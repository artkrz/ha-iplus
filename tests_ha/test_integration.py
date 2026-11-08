"""Exercise config flows and real HA sensor setup without HTTP."""
from unittest.mock import patch
import pytest
import requests
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.iplus.plus_balance import AuthenticationError, SMSRequired, PlusError
from custom_components.iplus.const import session_path

CREDS = {'username': 'user@example.com', 'password': 'secret'}

def entry(hass):
    value = MockConfigEntry(domain='iplus', data=CREDS, unique_id=CREDS['username'])
    value.add_to_hass(hass)
    return value

async def start(hass):
    return await hass.config_entries.flow.async_init('iplus', context={'source': 'user'})

async def test_success(hass, client):
    with patch('custom_components.iplus.async_setup_entry', return_value=True):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(result['flow_id'],
            {**CREDS, 'username': 'USER@example.com'})
        assert result['type'] is FlowResultType.CREATE_ENTRY
        assert result['data'] == CREDS
        assert result['result'].unique_id == CREDS['username']
        client.ensure_session.assert_called_once_with(code_provider=None)

async def test_sms(hass, client):
    client.ensure_session.side_effect = [SMSRequired(), None]
    with patch('custom_components.iplus.async_setup_entry', return_value=True):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(result['flow_id'], CREDS)
        assert result['step_id'] == 'sms'
        result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': '12x4'})
        assert result['errors'] == {'code': 'invalid_code'}
        result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': '1234'})
        assert result['type'] is FlowResultType.CREATE_ENTRY
        assert client.ensure_session.call_args.kwargs['code_provider']() == '1234'

@pytest.mark.parametrize(('error','expected'), [(AuthenticationError(), 'invalid_auth'),
    (PlusError(), 'cannot_connect'), (requests.ConnectionError(), 'cannot_connect')])
async def test_errors(hass, client, error, expected):
    client.ensure_session.side_effect = error
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], CREDS)
    assert result['errors'] == {'base': expected}

async def test_duplicate(hass, client):
    entry(hass)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], CREDS)
    assert result['reason'] == 'already_configured'
    client.ensure_session.assert_not_called()

@pytest.mark.parametrize('sms', [False, True])
async def test_reauth(hass, client, sms):
    value = entry(hass)
    path = session_path(hass, value.unique_id)
    await hass.async_add_executor_job(lambda: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text('{}')))
    if sms:
        client.ensure_session.side_effect = [SMSRequired(), None]
    with patch('custom_components.iplus.async_setup_entry', return_value=True):
        result = await hass.config_entries.flow.async_init('iplus', context={
            'source': config_entries.SOURCE_REAUTH, 'entry_id': value.entry_id}, data=value.data)
        assert result['step_id'] == 'reauth_confirm'
        result = await hass.config_entries.flow.async_configure(result['flow_id'], {'password': 'new'})
        if sms:
            assert result['step_id'] == 'sms'
            result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': '1234'})
        assert not path.exists()  # A changed password clears the previous failed chain.
        assert result['reason'] == 'reauth_successful'
        assert value.data['password'] == 'new'

async def test_sensors_options_cleanup(hass, client, balance):
    value = entry(hass)
    assert await hass.config_entries.async_setup(value.entry_id)
    await hass.async_block_till_done()
    states = hass.states.async_all('sensor')
    assert len(states) == 8
    for expected, icon in [('2.943', 'mdi:chart-bar'),
                           ('1.51', 'mdi:web-check'),
                           ('Plus Elastyczna na Kartę', 'mdi:card-account-details')]:
        sensor = next(s for s in states if s.attributes.get('icon') == icon)
        assert sensor.state == expected
        if icon != 'mdi:card-account-details':
            assert sensor.attributes['device_class'] == 'data_size'
            assert sensor.attributes['state_class'] == 'measurement'
            assert sensor.attributes['unit_of_measurement'] == 'GB'
        else:
            from homeassistant.helpers import entity_registry as er
            assert er.async_get(hass).async_get(sensor.entity_id).entity_category.value == 'diagnostic'
            assert 'unit_of_measurement' not in sensor.attributes
    history = next(s for s in states if s.attributes.get('icon') == 'mdi:chart-bar')
    assert history.attributes['last_usage'] == balance['subscriptions'][0]['last_usage']
    remaining = next(s for s in states if 'packages' in s.attributes)
    assert float(remaining.state) == balance['subscriptions'][0]['total_remaining_gb']
    assert remaining.attributes['unit_of_measurement'] == 'GB'
    assert remaining.attributes['state_class'] == 'measurement'
    assert remaining.attributes['device_class'] == 'data_size'
    assert remaining.attributes['packages'] == balance['subscriptions'][0]['packages']
    timestamp = next(s for s in states if s.attributes.get('device_class') == 'timestamp')
    assert timestamp.state == balance['subscriptions'][0]['valid_until'].isoformat()
    account = next(s for s in states if s.attributes.get('device_class') == 'monetary')
    assert account.state == '25.03'
    assert account.attributes['unit_of_measurement'] == 'PLN'
    assert account.attributes['state_class'] == 'total'
    assert account.attributes['icon'] == 'mdi:cash'
    account_expiry = next(s for s in states if s.entity_id.endswith('_account_valid_until'))
    assert account_expiry.state == '2027-10-28T12:17:06+00:00'
    balance['subscriptions'][0]['account'] = None
    value.runtime_data.async_set_updated_data(balance)
    await hass.async_block_till_done()
    assert hass.states.get(account.entity_id).state == 'unavailable'
    assert hass.states.get(account_expiry.entity_id).state == 'unavailable'
    assert hass.states.get(remaining.entity_id).state != 'unavailable'
    result = await hass.config_entries.options.async_init(value.entry_id)
    result = await hass.config_entries.options.async_configure(result['flow_id'], {'scan_interval': 15})
    await hass.async_block_till_done()
    assert value.options['scan_interval'] == 15
    assert value.runtime_data.update_interval.total_seconds() == 900
    path = session_path(hass, value.unique_id)
    await hass.async_add_executor_job(lambda: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text('{}')))
    await hass.config_entries.async_remove(value.entry_id)
    assert not path.exists()

@pytest.mark.parametrize('error', [AuthenticationError(), SMSRequired()])
async def test_poll_auth_failure(hass, client, error):
    value = entry(hass)
    assert await hass.config_entries.async_setup(value.entry_id)
    client.get_balance.side_effect = error
    with pytest.raises(ConfigEntryAuthFailed):
        await value.runtime_data._async_update_data()
    await hass.config_entries.async_unload(value.entry_id)


@pytest.mark.parametrize('unlimited', [False, True])
async def test_conditional_sensors(hass, client, balance, unlimited):
    balance['subscriptions'][0].update(
        voice={'remaining': None if unlimited else 12, 'total': 30, 'unlimited': unlimited},
        sms={'remaining': None if unlimited else 7, 'total': 10, 'unlimited': unlimited})
    value = entry(hass)
    assert await hass.config_entries.async_setup(value.entry_id)
    await hass.async_block_till_done()
    states = hass.states.async_all('sensor')
    assert len(states) == 10
    for icon, expected in [('mdi:phone', '12'), ('mdi:message-text', '7')]:
        sensor = next(s for s in states if s.attributes.get('icon') == icon)
        assert sensor.state == ('unknown' if unlimited else expected)
        assert sensor.attributes['unlimited'] is unlimited
        if icon == 'mdi:phone':
            assert sensor.attributes['unit_of_measurement'] == 'min'
    await hass.config_entries.async_unload(value.entry_id)


async def test_new_category_reloads_once(hass, client, balance):
    from copy import deepcopy
    value = entry(hass)
    assert await hass.config_entries.async_setup(value.entry_id)
    await hass.async_block_till_done()
    updated = deepcopy(balance)
    updated['subscriptions'][0]['voice'] = {'remaining': 10, 'total': 20, 'unlimited': False}
    with patch.object(hass.config_entries, 'async_reload', return_value=True) as reload:
        value.runtime_data.async_set_updated_data(updated)
        await hass.async_block_till_done()
        value.runtime_data.async_set_updated_data(updated)
        await hass.async_block_till_done()
        reload.assert_called_once_with(value.entry_id)
    await hass.config_entries.async_unload(value.entry_id)


async def test_new_sms_category_creates_sensor_after_reload(hass, client, balance):
    from copy import deepcopy
    value = entry(hass)
    assert await hass.config_entries.async_setup(value.entry_id)
    await hass.async_block_till_done()
    updated = deepcopy(balance)
    updated['subscriptions'][0]['sms'] = {'remaining': 15, 'total': 20, 'unlimited': False}
    client.get_balance.return_value = updated
    value.runtime_data.async_set_updated_data(updated)
    await hass.async_block_till_done()
    sms = next(s for s in hass.states.async_all('sensor') if s.attributes.get('icon') == 'mdi:message-text')
    assert sms.state == '15'
    with patch.object(hass.config_entries, 'async_reload', return_value=True) as reload:
        value.runtime_data.async_set_updated_data(updated)
        await hass.async_block_till_done()
        reload.assert_not_called()
    await hass.config_entries.async_unload(value.entry_id)
