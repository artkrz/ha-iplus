"""Poll the synchronous Plus client in the executor."""
from datetime import timedelta
import logging
import requests
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DEFAULT_SCAN_INTERVAL
from .plus_balance import AuthenticationError, SMSRequired, PlusError

class PlusCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, logging.getLogger(__name__), name="iplus",
                         config_entry=entry, update_interval=timedelta(
                             minutes=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)))
        self.client = client

    async def _async_update_data(self):
        try:
            return await self.hass.async_add_executor_job(self.client.get_balance)
        except (AuthenticationError, SMSRequired) as err:
            raise ConfigEntryAuthFailed("Plus authentication required") from err
        except (PlusError, requests.RequestException) as err:
            raise UpdateFailed("Cannot retrieve Plus balance") from err
