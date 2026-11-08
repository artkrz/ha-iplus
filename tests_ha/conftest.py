"""Offline Home Assistant integration fixtures."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from plus_balance.parser import parse_account_balance, parse_products, summarize_packages, parse_usage_history, used_data

pytest_plugins = ['pytest_homeassistant_custom_component']

@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield

@pytest.fixture
def balance():
    payload = json.loads((Path(__file__).parents[1] / 'tests/fixtures/products_data.json').read_text())
    packages = parse_products(payload)
    return {'subscriptions': [{'msisdn': '48123456789', 'packages': packages,
                               'used_gb': used_data(summarize_packages(packages)),
                               **parse_usage_history(json.loads((Path(__file__).parents[1] / 'tests/fixtures/data_usage_history.json').read_text())),
                               'tariff': json.loads((Path(__file__).parents[1] / 'tests/fixtures/tariff.json').read_text())['name'],
                               'account': parse_account_balance(json.loads((Path(__file__).parents[1] / 'tests/fixtures/account_balance.json').read_text())),
                               **summarize_packages(packages)}]}

@pytest.fixture
def client(balance):
    instance = MagicMock()
    instance.get_balance.return_value = balance
    with patch('custom_components.iplus.config_flow.PlusClient', return_value=instance), \
         patch('custom_components.iplus.PlusClient', return_value=instance):
        yield instance
