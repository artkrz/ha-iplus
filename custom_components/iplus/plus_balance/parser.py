"""Parse active data usages and summarize decimal telecom data units."""
from datetime import datetime
from math import fsum

DATA_FACTORS = {'KB': 1e-6, 'MB': 1e-3, 'GB': 1, 'TB': 1000}


def parse_products(payload: dict) -> list[dict]:
    packages = []
    for product in payload.get('products', []) or []:
        if product.get('status') != 'active':
            continue
        due = product.get('dueDate')
        valid_until = None if not due or due.startswith('0001-01-01') else datetime.fromisoformat(due.replace('Z', '+00:00'))
        for category in product.get('categories', []) or []:
            for usage in category.get('usages', []) or []:
                packages.append({
                    'category': category.get('productType'),
                    'name': product.get('name'), 'product_id': product.get('productId'),
                    'type': product.get('type'), 'remaining': usage.get('remaining'),
                    'total': usage.get('total'), 'unit': usage.get('unit'),
                    'unlimited': bool(usage.get('unlimited')), 'description': usage.get('description'),
                    'valid_until': valid_until, 'renews': product.get('nextBillingPeriodStatus') == 'renew',
                })
    return packages


def summarize_packages(packages: list[dict]) -> dict:
    """Sum limited data usages in GB (1 GB = 1000 MB); use earliest expiry."""
    factors = DATA_FACTORS
    limited = [p for p in packages if p.get('category', 'data') == 'data' and not p['unlimited'] and str(p['unit']).upper() in factors]
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


def used_data(summary: dict) -> float | None:
    """Return used package data only when both totals are known."""
    total, remaining = summary.get('total_gb'), summary.get('total_remaining_gb')
    return round(total - remaining, 3) if total is not None and remaining is not None else None


def summarize_category(packages: list[dict], category: str) -> dict | None:
    """Summarize active voice/SMS usages; preserve unknown units in packages."""
    usages = [p for p in packages if p.get('category') == category]
    if not usages:
        return None
    factors = {'min': 1, 's': 1 / 60, 'sek': 1 / 60} if category == 'voice' else {'szt': 1, 'sms': 1}
    limited = [p for p in usages if not p['unlimited'] and str(p['unit']).lower() in factors]
    unlimited = any(p['unlimited'] for p in usages)
    return {
        'remaining': None if unlimited or not limited else round(fsum(
            float(p['remaining'] or 0) * factors[p['unit'].lower()] for p in limited), 3),
        'total': None if unlimited or not limited else round(fsum(
            float(p['total'] or 0) * factors[p['unit'].lower()] for p in limited), 3),
        'unlimited': unlimited,
    }


def parse_usage_history(payload: dict) -> dict:
    """Sum decimal data usage and find the newest nonzero usage."""
    history = payload.get('history', []) or []
    dates = [datetime.fromisoformat(p['date'].replace('Z', '+00:00'))
             for p in history if float(p.get('usage') or 0) > 0]
    return {
        'data_used_30d_gb': round(fsum(float(p.get('usage') or 0) * DATA_FACTORS[str(p['unit']).upper()]
                                     for p in history), 3),
        'last_usage': max(dates).isoformat() if dates else None,
    }
