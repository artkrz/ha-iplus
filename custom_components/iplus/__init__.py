"""Plus prepaid balance integration."""
from homeassistant.const import Platform, CONF_USERNAME, CONF_PASSWORD
from .const import session_path
from .coordinator import PlusCoordinator
from .plus_balance import PlusClient

async def async_setup_entry(hass, entry):
    client = await hass.async_add_executor_job(
        lambda: PlusClient(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
                           session_path=session_path(hass, entry.unique_id)))
    coordinator = PlusCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True

async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])

async def async_remove_entry(hass, entry):
    await hass.async_add_executor_job(
        lambda: session_path(hass, entry.unique_id).unlink(missing_ok=True))
