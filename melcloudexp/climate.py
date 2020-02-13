"""Platform for climate integration."""
from abc import ABC
from datetime import timedelta
import logging
from typing import Any, Dict, List, Optional

from pymelcloud import DEVICE_TYPE_ATA, DEVICE_TYPE_ATW, AtaDevice, AtwDevice
import pymelcloud.ata_device as ata
import pymelcloud.atw_device as atw
from pymelcloud.atw_device import (
    PROPERTY_ZONE_1_OPERATION_MODE,
    PROPERTY_ZONE_2_OPERATION_MODE,
    Zone,
)

from homeassistant.components.climate import ClimateDevice
from homeassistant.components.climate.const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util.temperature import convert as convert_temperature

from . import MelCloudDevice
from .const import ATTR_STATUS, DOMAIN, TEMP_UNIT_LOOKUP

SCAN_INTERVAL = timedelta(seconds=60)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType, entry: ConfigEntry, async_add_entities
):
    """Set up MelCloud device climate based on config_entry."""
    mel_devices = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AtaDeviceClimate(mel_device, mel_device.device)
            for mel_device in mel_devices[DEVICE_TYPE_ATA]
        ]
        + [
            AtwDeviceZoneClimate(mel_device, mel_device.device, zone)
            for mel_device in mel_devices[DEVICE_TYPE_ATW]
            for zone in mel_device.device.zones
        ],
        True,
    )


class MelCloudClimate(ClimateDevice, ABC):
    """Base climate device."""

    def __init__(self, device: MelCloudDevice):
        """Initialize the climate."""
        self.api = device
        self._base_device = self.api.device
        self._name = device.name

    async def async_update(self):
        """Update state from MELCloud."""
        await self.api.async_update()

    @property
    def device_info(self):
        """Return a device description for device registry."""
        return self.api.device_info

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self._base_device.set({"power": True})

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self._base_device.set({"power": False})

    @property
    def target_temperature_step(self) -> Optional[float]:
        """Return the supported step of target temperature."""
        return self._base_device.temperature_increment


ATA_HVAC_MODE_LOOKUP = {
    ata.OPERATION_MODE_HEAT: HVAC_MODE_HEAT,
    ata.OPERATION_MODE_DRY: HVAC_MODE_DRY,
    ata.OPERATION_MODE_COOL: HVAC_MODE_COOL,
    ata.OPERATION_MODE_FAN_ONLY: HVAC_MODE_FAN_ONLY,
    ata.OPERATION_MODE_HEAT_COOL: HVAC_MODE_HEAT_COOL,
}
ATA_HVAC_MODE_REVERSE_LOOKUP = {v: k for k, v in ATA_HVAC_MODE_LOOKUP.items()}


class AtaDeviceClimate(MelCloudClimate):
    """Air-to-Air climate device."""

    def __init__(self, device: MelCloudDevice, ata_device: AtaDevice):
        """Initialize the climate."""
        super().__init__(device)
        self._device = ata_device

    @property
    def unique_id(self) -> Optional[str]:
        """Return a unique ID."""
        return f"{self.api.device.serial}-{self.api.device.mac}"

    @property
    def name(self):
        """Return the display name of this entity."""
        return self._name

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        return TEMP_UNIT_LOOKUP.get(self._device.temp_unit, TEMP_CELSIUS)

    @property
    def hvac_mode(self) -> str:
        """Return hvac operation ie. heat, cool mode."""
        mode = self._device.operation_mode
        if not self._device.power or mode is None:
            return HVAC_MODE_OFF
        return ATA_HVAC_MODE_LOOKUP.get(mode)

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVAC_MODE_OFF:
            await self._device.set({"power": False})
            return

        operation_mode = ATA_HVAC_MODE_REVERSE_LOOKUP.get(hvac_mode)
        if operation_mode is None:
            raise ValueError(f"Invalid hvac_mode [{hvac_mode}]")

        props = {"operation_mode": operation_mode}
        if self.hvac_mode == HVAC_MODE_OFF:
            props["power"] = True
        await self._device.set(props)

    @property
    def hvac_modes(self) -> List[str]:
        """Return the list of available hvac operation modes."""
        return [HVAC_MODE_OFF] + [
            ATA_HVAC_MODE_LOOKUP.get(mode) for mode in self._device.operation_modes
        ]

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._device.room_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._device.target_temperature

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        await self._device.set(
            {"target_temperature": kwargs.get("temperature", self.target_temperature)}
        )

    @property
    def fan_mode(self) -> Optional[str]:
        """Return the fan setting."""
        return self._device.fan_speed

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self._device.set({"fan_speed": fan_mode})

    @property
    def fan_modes(self) -> Optional[List[str]]:
        """Return the list of available fan modes."""
        return self._device.fan_speeds

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return SUPPORT_FAN_MODE | SUPPORT_TARGET_TEMPERATURE

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        min_value = self._device.target_temperature_min
        if min_value is not None:
            return min_value

        return convert_temperature(
            DEFAULT_MIN_TEMP, TEMP_CELSIUS, self.temperature_unit
        )

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        max_value = self._device.target_temperature_max
        if max_value is not None:
            return max_value

        return convert_temperature(
            DEFAULT_MAX_TEMP, TEMP_CELSIUS, self.temperature_unit
        )


ATW_ZONE_HVAC_MODE_LOOKUP = {
    atw.ZONE_OPERATION_MODE_HEAT: HVAC_MODE_HEAT,
    atw.ZONE_OPERATION_MODE_COOL: HVAC_MODE_COOL,
}
ATW_ZONE_HVAC_MODE_REVERSE_LOOKUP = {v: k for k, v in ATW_ZONE_HVAC_MODE_LOOKUP.items()}


class AtwDeviceZoneClimate(MelCloudClimate):
    """Air-to-Water zone climate device."""

    def __init__(self, device: MelCloudDevice, atw_device: AtwDevice, atw_zone: Zone):
        """Initialize the climate."""
        super().__init__(device)
        self._device = atw_device
        self._zone = atw_zone

    @property
    def unique_id(self) -> Optional[str]:
        """Return a unique ID."""
        return f"{self.api.device.serial}-{self.api.device.mac}-{self._zone.zone_index}"

    @property
    def name(self) -> str:
        """Return the display name of this entity."""
        return f"{self._name} {self._zone.name}"

    @property
    def state_attributes(self) -> Dict[str, Any]:
        """Return the optional state attributes with device specific additions."""
        data = super().state_attributes
        data[ATTR_STATUS] = ATW_ZONE_HVAC_MODE_LOOKUP.get(
            self._zone.state, self._zone.state,
        )
        return data

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        return TEMP_UNIT_LOOKUP.get(self._device.temp_unit, TEMP_CELSIUS)

    @property
    def hvac_mode(self) -> str:
        """Return hvac operation ie. heat, cool mode."""
        mode = self._zone.operation_mode
        if not self._device.power or mode is None:
            return HVAC_MODE_OFF
        return ATW_ZONE_HVAC_MODE_LOOKUP.get(mode, HVAC_MODE_OFF)

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVAC_MODE_OFF:
            await self._device.set({"power": False})
            return

        operation_mode = ATW_ZONE_HVAC_MODE_REVERSE_LOOKUP.get(hvac_mode)
        if operation_mode is None:
            raise ValueError(f"Invalid hvac_mode [{hvac_mode}]")

        if self._zone.zone_index == 1:
            props = {PROPERTY_ZONE_1_OPERATION_MODE: operation_mode}
        else:
            props = {PROPERTY_ZONE_2_OPERATION_MODE: operation_mode}
        if self.hvac_mode == HVAC_MODE_OFF:
            props["power"] = True
        await self._device.set(props)

    @property
    def hvac_modes(self) -> List[str]:
        """Return the list of available hvac operation modes."""
        return [self.hvac_mode]

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._zone.room_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._zone.target_temperature

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        await self._zone.set_target_temperature(
            kwargs.get("temperature", self.target_temperature)
        )

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        # TODO: Dig out the real min temp
        return convert_temperature(10, TEMP_CELSIUS, self.temperature_unit)

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        # TODO: Dig out the real max temp
        return convert_temperature(30, TEMP_CELSIUS, self.temperature_unit)
