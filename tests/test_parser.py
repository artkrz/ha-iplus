import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plus_balance.parser import parse_products, summarize_packages


def test_fixture():
    payload = json.loads((Path(__file__).parent / 'fixtures/products_data.json').read_text())
    packages = parse_products(payload)
    assert len(packages) == 1
    assert packages[0] == {
        'name': 'GB za doładowania', 'product_id': '7851', 'type': 'Package',
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
    assert len(packages) == 1
    assert packages[0]['valid_until'] is None
    assert packages[0]['renews'] is False
    assert summarize_packages(packages) == {'total_remaining_gb': 0, 'total_gb': 0, 'valid_until': None}
    assert parse_products({'products': [{'status': 'active', 'categories': None}]}) == []
