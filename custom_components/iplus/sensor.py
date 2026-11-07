"""Per-subscription data sensors."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(PlusSensor(coordinator, subscription["msisdn"], key)
                       for subscription in coordinator.data["subscriptions"]
                       for key in ("remaining_data", "total_data", "valid_until"))

class PlusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, msisdn, key):
        super().__init__(coordinator)
        self.msisdn, self.key = msisdn, key
        self._attr_unique_id = f"{msisdn}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, msisdn)},
            name=f"Plus {msisdn}", manufacturer="Plus", model="Prepaid")
        if key == "valid_until":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        else:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
            self._attr_icon = "mdi:web"

    @property
    def subscription(self):
        return next((s for s in self.coordinator.data["subscriptions"]
                     if s["msisdn"] == self.msisdn), {})

    @property
    def available(self):
        return super().available and bool(self.subscription)

    @property
    def native_value(self):
        value = self.subscription.get({"remaining_data": "total_remaining_gb",
            "total_data": "total_gb", "valid_until": "valid_until"}[self.key])
        if self.key == "valid_until" and isinstance(value, str):
            return dt_util.parse_datetime(value)
        return value

    @property
    def extra_state_attributes(self):
        if self.key == "remaining_data":
            return {"packages": self.subscription.get("packages", [])}
        return None
