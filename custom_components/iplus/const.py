"""Integration constants and stable session paths."""
from hashlib import sha256
from pathlib import Path

DOMAIN = "iplus"
DEFAULT_SCAN_INTERVAL = 60

def session_path(hass, username):
    slug = sha256(username.lower().encode()).hexdigest()
    return Path(hass.config.path(".storage", f"iplus_{slug}.json"))
