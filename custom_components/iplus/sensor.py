"""Per-subscription data sensors."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    keys = ("remaining_data", "total_data", "valid_until", "account_balance",
            "account_valid_until", "data_used_30d", "tariff", "used_data")
    categories = {(s["msisdn"], category) for s in coordinator.data["subscriptions"]
                  for category in ("voice", "sms") if s.get(category) is not None}
    async_add_entities(
        PlusSensor(coordinator, subscription["msisdn"], key)
        for subscription in coordinator.data["subscriptions"]
        for key in (*keys, *(key for category, key in (
            ("voice", "remaining_minutes"), ("sms", "remaining_sms"))
            if (subscription["msisdn"], category) in categories))
    )
    reload_pending = False

    def check_categories():
        nonlocal reload_pending
        current = {(s["msisdn"], category) for s in coordinator.data["subscriptions"]
                   for category in ("voice", "sms") if s.get(category) is not None}
        if current - categories and not reload_pending:
            reload_pending = True
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    entry.async_on_unload(coordinator.async_add_listener(check_categories))

class PlusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, msisdn, key):
        super().__init__(coordinator)
        self.msisdn, self.key = msisdn, key
        self._attr_unique_id = f"{msisdn}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, msisdn)},
            name=f"Plus {msisdn}", manufacturer="Plus", model="Prepaid")
        if key in ("valid_until", "account_valid_until"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key == "account_balance":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_native_unit_of_measurement = "PLN"
            self._attr_icon = "mdi:cash"
            self._attr_suggested_display_precision = 2
        elif key == "tariff":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_icon = "mdi:card-account-details"
        elif key in ("remaining_minutes", "remaining_sms"):
            self._attr_icon = "mdi:phone" if key == "remaining_minutes" else "mdi:message-text"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if key == "remaining_minutes":
                self._attr_native_unit_of_measurement = "min"
        else:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
            self._attr_icon = {"data_used_30d": "mdi:chart-bar", "used_data": "mdi:web-check"}.get(key, "mdi:web")

    @property
    def subscription(self):
        return next((s for s in self.coordinator.data["subscriptions"]
                     if s["msisdn"] == self.msisdn), {})

    @property
    def available(self):
        return (super().available and bool(self.subscription)
                and (not self.key.startswith("account_") or self.subscription.get("account") is not None))

    @property
    def native_value(self):
        if self.key.startswith("account_"):
            account = self.subscription.get("account") or {}
            value = account.get("amount" if self.key == "account_balance" else "account_valid_until")
        elif self.key in ("remaining_minutes", "remaining_sms"):
            value = (self.subscription.get("voice" if self.key == "remaining_minutes" else "sms") or {}).get("remaining")
        else:
            value = self.subscription.get({"remaining_data": "total_remaining_gb",
            "total_data": "total_gb", "valid_until": "valid_until",
            "data_used_30d": "data_used_30d_gb", "tariff": "tariff", "used_data": "used_gb"}[self.key])
        if self.key in ("valid_until", "account_valid_until") and isinstance(value, str):
            return dt_util.parse_datetime(value)
        return value

    @property
    def extra_state_attributes(self):
        if self.key == "remaining_data":
            return {"packages": self.subscription.get("packages", [])}
        if self.key == "data_used_30d":
            return {"last_usage": self.subscription.get("last_usage")}
        if self.key in ("remaining_minutes", "remaining_sms"):
            return self.subscription.get("voice" if self.key == "remaining_minutes" else "sms")
        return None
