import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plus_balance.parser import parse_account_balance, parse_products, summarize_packages


def test_fixture():
    payload = json.loads((Path(__file__).parent / 'fixtures/products_data.json').read_text())
    packages = parse_products(payload)
    assert len(packages) == 1
    assert packages[0] == {
        'category': 'data', 'name': 'GB za doładowania', 'product_id': '7851', 'type': 'Package',
        'remaining': 8.49, 'total': 10, 'unit': 'GB', 'unlimited': False,
        'description': 'w Polsce', 'valid_until': datetime(2026, 12, 7, 9, 33, 48, tzinfo=timezone.utc),
        'renews': True,
    }
    assert summarize_packages(packages) == {
        'total_remaining_gb': 8.49, 'total_gb': 10, 'valid_until': packages[0]['valid_until'],
    }


@pytest.mark.parametrize(('unit', 'amount'), [('KB', 1000000), ('MB', 1000), ('GB', 1), ('TB', .001)])
def test_unit_conversion(unit, amount):
    package = dict(remaining=amount, total=amount * 2, unit=unit, unlimited=False, valid_until=None)
    assert summarize_packages([package]) == {'total_remaining_gb': 1, 'total_gb': 2, 'valid_until': None}


def test_filters_and_missing_expiry():
    product = dict(status='active', dueDate='0001-01-01T00:00:00Z', categories=[
        dict(productType='voice', usages=[dict(remaining=5, total=10, unit='GB')]),
        dict(productType='data', usages=[dict(unlimited=True, unit='GB')]),
    ])
    packages = parse_products({'products': [product, {**product, 'status': 'inactive'}]})
    assert len(packages) == 2
    assert packages[0]['valid_until'] is None
    assert packages[0]['renews'] is False
    assert summarize_packages(packages) == {'total_remaining_gb': 0, 'total_gb': 0, 'valid_until': None}
    assert parse_products({'products': [{'status': 'active', 'categories': None}]}) == []


def test_account_balance_fixture():
    payload = json.loads((Path(__file__).parent / 'fixtures/account_balance.json').read_text())
    assert parse_account_balance(payload) == {
        'amount': 25.03, 'currency': 'PLN',
        'account_valid_until': '2027-10-28T13:17:06+01:00', 'overdue_amount': 0.0,
    }


def test_account_balance_missing_expiry():
    assert parse_account_balance({'balance': {'amount': '0', 'overdueAmount': '1.5'}}) == {
        'amount': 0.0, 'currency': 'PLN', 'account_valid_until': None, 'overdue_amount': 1.5,
    }


def test_history_fixture():
    from plus_balance.parser import parse_usage_history
    payload = json.loads((Path(__file__).parent / 'fixtures/data_usage_history.json').read_text())
    assert parse_usage_history(payload) == {
        'data_used_30d_gb': 2.943, 'last_usage': '2026-11-03T10:23:19+01:00'}
    assert parse_usage_history({'history': []}) == {'data_used_30d_gb': 0, 'last_usage': None}


def test_synthetic_voice_sms():
    # Synthetic products: no live voice/SMS sample is available.
    from plus_balance.parser import summarize_category, used_data
    product = {'status': 'active', 'categories': [
        {'productType': 'voice', 'usages': [
            {'remaining': 60, 'total': 120, 'unit': 's'},
            {'remaining': 2, 'total': 4, 'unit': 'MIN'},
            {'remaining': 60, 'total': 120, 'unit': 'sek'},
            {'remaining': 100, 'total': 200, 'unit': 'unknown'}]},
        {'productType': 'sms_mms', 'usages': [
            {'remaining': 5, 'total': 10, 'unit': 'szt'},
            {'remaining': 3, 'total': 5, 'unit': 'SMS'}]}]}
    packages = parse_products({'products': [product]})
    assert len(packages) == 6
    assert summarize_category(packages, 'voice') == {'remaining': 4, 'total': 8, 'unlimited': False}
    assert summarize_category(packages, 'sms_mms') == {'remaining': 8, 'total': 15, 'unlimited': False}
    assert summarize_category([], 'voice') is None
    assert summarize_packages(packages)['total_gb'] == 0
    for category in ('voice', 'sms_mms'):
        packages.append({'category': category, 'unlimited': True, 'unit': None})
        assert summarize_category(packages, category) == {'remaining': None, 'total': None, 'unlimited': True}
    assert used_data({'total_gb': 10, 'total_remaining_gb': 8.49}) == 1.51
    assert used_data({}) is None
    assert used_data({'total_gb': None, 'total_remaining_gb': 1}) is None


def test_history_units_and_chronological_latest():
    from plus_balance.parser import parse_usage_history
    assert parse_usage_history({'history': [
        {'date': '2026-11-03T12:00:00+02:00', 'usage': 1, 'unit': 'GB'},
        {'date': '2026-11-03T10:30:00Z', 'usage': 1000, 'unit': 'KB'},
        {'date': '2026-11-04T00:00:00Z', 'usage': 0, 'unit': 'MB'},
    ]}) == {'data_used_30d_gb': 1.001, 'last_usage': '2026-11-03T10:30:00+00:00'}
