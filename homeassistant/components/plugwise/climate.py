"""Plugwise Climate component for Home Assistant."""
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_MAX_TEMP, DEFAULT_MIN_TEMP, DOMAIN, SCHEDULE_OFF, SCHEDULE_ON
from .coordinator import PlugwiseDataUpdateCoordinator
from .entity import PlugwiseEntity
from .util import plugwise_command

HVAC_MODES_HEAT_ONLY = [HVAC_MODE_HEAT, HVAC_MODE_AUTO, HVAC_MODE_OFF]
HVAC_MODES_HEAT_COOL = [HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_AUTO, HVAC_MODE_OFF]
THERMOSTAT_CLASSES = ["thermostat", "zone_thermostat", "thermostatic_radiator_valve"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Smile Thermostats from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        PlugwiseClimateEntity(coordinator, device_id)
        for device_id, device in coordinator.data.devices.items()
        if device["class"] in THERMOSTAT_CLASSES
    )


class PlugwiseClimateEntity(PlugwiseEntity, ClimateEntity):
    """Representation of an Plugwise thermostat."""

    _attr_hvac_mode = HVAC_MODE_HEAT
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_preset_mode = None
    _attr_preset_modes = None
    _attr_supported_features = SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE
    _attr_temperature_unit = TEMP_CELSIUS
    _attr_hvac_modes = HVAC_MODES_HEAT_ONLY
    _attr_hvac_mode = HVAC_MODE_HEAT

    def __init__(
        self,
        coordinator: PlugwiseDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Set up the Plugwise API."""
        super().__init__(coordinator, device_id)
        self._attr_extra_state_attributes = {}
        self._attr_unique_id = f"{device_id}-climate"
        self._attr_name = coordinator.data.devices[device_id].get("name")

        self._loc_id = coordinator.data.devices[device_id]["location"]

    @plugwise_command
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ((temperature := kwargs.get(ATTR_TEMPERATURE)) is None) or (
            self._attr_max_temp < temperature < self._attr_min_temp
        ):
            raise ValueError("Invalid temperature requested")
        await self.coordinator.api.set_temperature(self._loc_id, temperature)

    @plugwise_command
    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set the hvac mode."""
        state = SCHEDULE_OFF
        climate_data = self.coordinator.data.devices[self._dev_id]

        if hvac_mode == HVAC_MODE_AUTO:
            state = SCHEDULE_ON
            await self.coordinator.api.set_temperature(
                self._loc_id, climate_data.get("schedule_temperature")
            )
            self._attr_target_temperature = climate_data.get("schedule_temperature")

        await self.coordinator.api.set_schedule_state(
            self._loc_id, climate_data.get("last_used"), state
        )

    @plugwise_command
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        if not self.coordinator.data.devices[self._dev_id].get("presets"):
            raise ValueError("No presets available")

        await self.coordinator.api.set_preset(self._loc_id, preset_mode)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data.devices[self._dev_id]
        heater_central_data = self.coordinator.data.devices[
            self.coordinator.data.gateway["heater_id"]
        ]

        # Current & set temperatures
        if setpoint := data["sensors"].get("setpoint"):
            self._attr_target_temperature = setpoint
        if temperature := data["sensors"].get("temperature"):
            self._attr_current_temperature = temperature

        # Presets handling
        self._attr_preset_mode = data.get("active_preset")
        if presets := data.get("presets"):
            self._attr_preset_modes = list(presets)
        else:
            self._attr_preset_mode = None

        # Determine current hvac action
        self._attr_hvac_action = CURRENT_HVAC_IDLE
        if heater_central_data.get("heating_state"):
            self._attr_hvac_action = CURRENT_HVAC_HEAT
        elif heater_central_data.get("cooling_state"):
            self._attr_hvac_action = CURRENT_HVAC_COOL

        # Determine hvac modes and current hvac mode
        self._attr_hvac_modes = HVAC_MODES_HEAT_ONLY
        if self.coordinator.data.gateway.get("cooling_present"):
            self._attr_hvac_modes = HVAC_MODES_HEAT_COOL
        if data.get("mode") in self._attr_hvac_modes:
            self._attr_hvac_mode = data["mode"]

        # Extra attributes
        self._attr_extra_state_attributes = {
            "available_schemas": data.get("available_schedules"),
            "selected_schema": data.get("selected_schedule"),
        }

        super()._handle_coordinator_update()
