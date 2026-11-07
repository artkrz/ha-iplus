"""Parse active data usages and summarize decimal telecom data units."""
from datetime import datetime
from math import fsum


def parse_products(payload: dict) -> list[dict]:
    packages = []
    for product in payload.get('products', []) or []:
        if product.get('status') != 'active':
            continue
        due = product.get('dueDate')
        valid_until = None if not due or due.startswith('0001-01-01') else datetime.fromisoformat(due.replace('Z', '+00:00'))
        for category in product.get('categories', []) or []:
            if category.get('productType') != 'data':
                continue
            for usage in category.get('usages', []) or []:
                packages.append({
                    'name': product.get('name'), 'product_id': product.get('productId'),
                    'type': product.get('type'), 'remaining': usage.get('remaining'),
                    'total': usage.get('total'), 'unit': usage.get('unit'),
                    'unlimited': bool(usage.get('unlimited')), 'description': usage.get('description'),
                    'valid_until': valid_until, 'renews': product.get('nextBillingPeriodStatus') == 'renew',
                })
    return packages


def summarize_packages(packages: list[dict]) -> dict:
    """Sum limited data usages in GB (1 GB = 1000 MB); use earliest expiry."""
    factors = {'KB': 1e-6, 'MB': 1e-3, 'GB': 1, 'TB': 1000}
    limited = [p for p in packages if not p['unlimited'] and str(p['unit']).upper() in factors]
    dates = [p['valid_until'] for p in limited if p['valid_until'] is not None]
    return {
        'total_remaining_gb': fsum(float(p['remaining'] or 0) * factors[p['unit'].upper()] for p in limited),
        'total_gb': fsum(float(p['total'] or 0) * factors[p['unit'].upper()] for p in limited),
        'valid_until': min(dates) if dates else None,
    }


def parse_account_balance(payload: dict) -> dict:
    """Parse prepaid funds and account validity, independently of data packages."""
    balance = payload['balance']
    return {
        'amount': float(balance['amount']),
        'currency': 'PLN',
        'account_valid_until': balance.get('expiryDate') or None,
        'overdue_amount': float(balance.get('overdueAmount', 0)),
    }
