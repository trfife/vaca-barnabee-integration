"""Sensor for Wyoming."""

from __future__ import annotations

from functools import reduce
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import LIGHT_LUX, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.dt import now, parse_datetime

from .const import DOMAIN
from ._censor import censor
from .devices import VASatelliteDevice
from .entity import VASatelliteEntity

if TYPE_CHECKING:
    from homeassistant.components.wyoming import DomainDataItem

UNKNOWN: str = "unknown"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    item: DomainDataItem = hass.data[DOMAIN][config_entry.entry_id]
    device: VASatelliteDevice = item.device  # type: ignore[assignment]

    # Setup is only forwarded for satellites
    assert item.device is not None

    entities = [
        WyomingSatelliteSTTSensor(device),
        WyomingSatelliteTTSSensor(device),
        WyomingSatelliteIntentSensor(device),
        WyomingSatelliteOrientationSensor(device),
        WyomingSatelliteBrowserPathSensor(device),
        WyomingSatelliteStateSensor(device),
        WyomingSatellitePipelineStageSensor(device),
        WyomingSatelliteLastWakeSensor(device),
        WyomingSatelliteLastPipelineSuccessSensor(device),
        WyomingSatelliteLastErrorSensor(device),
        WyomingSatelliteMicPeakLevelSensor(device),
        WyomingSatelliteMicRmsLevelSensor(device),
    ]

    if capabilities := device.capabilities:
        if capabilities.get("app_version"):
            entities.append(WyomingSatelliteAppVersionSensor(device))
        if capabilities.get("has_battery"):
            entities.append(WyomingSatelliteBatteryLevelSensor(device))
        if device.has_light_sensor():
            entities.append(WyomingSatelliteLightSensor(device))
        if capabilities.get("has_front_camera"):
            entities.append(WyomingSatelliteLastMotionSensor(device))

    async_add_entities(entities)


class WyomingSatelliteSTTSensor(VASatelliteEntity, RestoreSensor):
    """Entity to represent STT sensor for satellite."""

    entity_description = SensorEntityDescription(
        key="stt",
        translation_key="stt",
        icon="mdi:microphone-message",
    )
    _attr_native_value = UNKNOWN

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None:
            self._value_changed(state.state)

        self._device.set_stt_listener(self._value_changed)

    @callback
    def _value_changed(self, value: str) -> None:
        """Call when value changed."""
        if value:
            value = censor(value) or value
            if len(value) > 254:
                # Limit the length of the value to avoid issues with Home Assistant
                value = value[:252] + ".."
            self._attr_native_value = value
            self.async_write_ha_state()


class WyomingSatelliteTTSSensor(VASatelliteEntity, RestoreSensor):
    """Entity to represent TTS sensor for satellite."""

    entity_description = SensorEntityDescription(
        key="tts", translation_key="tts", icon="mdi:speaker-message"
    )
    _attr_native_value = UNKNOWN

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None:
            self._value_changed(state.state)

        self._device.set_tts_listener(self._value_changed)

    @callback
    def _value_changed(self, value: str) -> None:
        """Call when value changed."""
        if value:
            value = censor(value) or value
            if len(value) > 254:
                # Limit the length of the value to avoid issues with Home Assistant
                value = value[:252] + ".."
            self._attr_native_value = value
            self.async_write_ha_state()


class WyomingSatelliteIntentSensor(VASatelliteEntity, RestoreSensor):
    """Entity to represent intent sensor for satellite."""

    entity_description = SensorEntityDescription(
        key="intent", translation_key="intent", icon="mdi:message-bulleted"
    )
    _attr_native_value = UNKNOWN

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None:
            self._attr_native_value = state.state
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._device.device_id}_intent_output",
                self.status_update,
            )
        )

    @callback
    def status_update(self, data: dict[str, Any]) -> None:
        """Update entity."""
        if data and data.get("intent_output"):
            value = str(
                self.get_key("intent_output.response.speech.plain.speech", data)
            )
            if value:
                value = censor(value) or value
                if len(value) > 254:
                    # Limit the length of the value to avoid issues with Home Assistant
                    value = value[:252] + ".."
                self._attr_native_value = value

            self._attr_extra_state_attributes = data
            self.async_write_ha_state()

    def get_key(
        self, dot_notation_path: str, data: dict
    ) -> dict[str, dict | str | int] | str | int | None:
        """Try to get a deep value from a dict based on a dot-notation."""

        try:
            if "." in dot_notation_path:
                dn_list = dot_notation_path.split(".")
            else:
                dn_list = [dot_notation_path]
            return reduce(dict.get, dn_list, data)  # type: ignore[return-value]
        except (TypeError, KeyError):
            return None


class _WyomingSatelliteDeviceSensorBase(VASatelliteEntity, RestoreSensor):
    """Base class for device sensors."""

    _attr_native_value = 0
    _listener_class = "status_update"

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None:
            if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
                self._attr_native_value = self._get_timestamp_from_string(state.state)
            else:
                self._attr_native_value = state.state
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._device.device_id}_{self._listener_class}",
                self.status_update,
            )
        )

    def _get_native_value(self, value: Any) -> Any:
        """Get the native value from the data."""
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            return value
        return value

    def _get_timestamp_from_string(self, timestamp_str: str) -> Any:
        """Convert timestamp string to datetime object."""
        if timestamp_str.startswith("1970-01-01"):
            return None
        if parsed_time := parse_datetime(timestamp_str):
            if parsed_time > now(parsed_time.tzinfo):
                return now(parsed_time.tzinfo)
            return parsed_time
        return None

    @callback
    def status_update(self, data: dict[str, Any]) -> None:
        """Update entity."""
        if self._listener_class == "status_update":
            if sensors := data.get("sensors"):
                if self.entity_description.key in sensors:
                    if (
                        self.entity_description.device_class
                        == SensorDeviceClass.TIMESTAMP
                    ):
                        # Handle timestamp conversion
                        timestamp_str = sensors[self.entity_description.key]
                        self._attr_native_value = self._get_timestamp_from_string(
                            timestamp_str
                        )
                    else:
                        self._attr_native_value = self._get_native_value(
                            sensors[self.entity_description.key]
                        )
                    self.async_write_ha_state()
        elif self._listener_class == "capabilities_update":
            if self._device.capabilities and self._device.capabilities.get(
                self.entity_description.key
            ):
                self._attr_native_value = self._get_native_value(
                    self._device.capabilities[self.entity_description.key]
                )
                self.async_write_ha_state()


class WyomingSatelliteLightSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent light sensor for satellite."""

    entity_description = SensorEntityDescription(
        key="light",
        translation_key="light_level",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        suggested_display_precision=0,
    )


class WyomingSatelliteOrientationSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent orientation sensor for satellite."""

    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="orientation", translation_key="orientation", icon="mdi:screen-rotation"
    )


class WyomingSatelliteBatteryLevelSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent battery level sensor for satellite."""

    entity_description = SensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
    )


class WyomingSatelliteBrowserPathSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent browser path sensor for satellite."""

    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="current_path", translation_key="current_path", icon="mdi:web"
    )


class WyomingSatelliteLastMotionSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent last motion for satellite."""

    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="last_motion",
        translation_key="last_motion",
        icon="mdi:motion-sensor",
        device_class=SensorDeviceClass.TIMESTAMP,
    )


class WyomingSatelliteAppVersionSensor(_WyomingSatelliteDeviceSensorBase):
    """Entity to represent app version sensor for satellite."""

    _listener_class = "capabilities_update"
    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="app_version",
        translation_key="app_version",
        icon="mdi:application",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def _get_native_value(self, value: Any) -> Any:
        """Get the native value from the data."""
        return value if value is not None else UNKNOWN

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity attributes."""
        return {
            "device_signature": self.get_capability("device_signature"),
            "android_version": self.get_capability("release"),
            "webview_version": self.get_capability("webview_version"),
            "has_battery": self.get_capability("has_battery"),
            "has_front_camera": self.get_capability("has_front_camera"),
            "has_light_sensor": self._device.has_light_sensor(),
            "sensors": self.get_sensor_names(),
        }

    def get_capability(self, capability: str) -> Any:
        """Get a specific capability from the device."""
        if self._device.capabilities is None:
            return UNKNOWN
        return self._device.capabilities.get(capability, UNKNOWN)

    def get_sensor_names(self) -> list[str] | None:
        """Get the names of all sensors."""
        if self._device.capabilities and (
            sensors := self._device.capabilities.get("sensors")
        ):
            return [sensor.get("name") for sensor in sensors]
        return None


# --- Barnabee fork: dashboard-visibility sensors ---------------------------
#
# These are fed by the satellite's periodic status heartbeat
# (P4.5a / commit e3b1aad on vaca-barnabee-android). The phone pushes
# `sensors.satellite_state` etc. on every pipeline transition plus a ~14s
# timer, so HA's `last_updated` stays fresh even when idle.
#
# `satellite_state` is the coarse user-facing phase used by the Barnabee
# dashboard to show listening / thinking / talking badges. `pipeline_stage`
# is the fine-grained internal stage, surfaced as a diagnostic entity.

SATELLITE_PHASE_OPTIONS = [
    "idle",
    "listening",
    "thinking",
    "talking",
    "error",
    "paused",
]


class WyomingSatelliteStateSensor(_WyomingSatelliteDeviceSensorBase):
    """Coarse pipeline phase for the Barnabee dashboard."""

    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="satellite_state",
        name="Satellite state",
        icon="mdi:account-voice",
        device_class=SensorDeviceClass.ENUM,
        options=SATELLITE_PHASE_OPTIONS,
    )


class WyomingSatellitePipelineStageSensor(_WyomingSatelliteDeviceSensorBase):
    """Fine-grained pipeline stage (diagnostic)."""

    _attr_native_value = UNKNOWN
    entity_description = SensorEntityDescription(
        key="pipeline_stage",
        name="Pipeline stage",
        icon="mdi:pipe",
        entity_category=EntityCategory.DIAGNOSTIC,
    )


class WyomingSatelliteLastWakeSensor(_WyomingSatelliteDeviceSensorBase):
    """Timestamp of the last wake-word detection."""

    _attr_native_value = None
    entity_description = SensorEntityDescription(
        key="last_wake_at",
        name="Last wake",
        icon="mdi:ear-hearing",
        device_class=SensorDeviceClass.TIMESTAMP,
    )


class WyomingSatelliteLastPipelineSuccessSensor(_WyomingSatelliteDeviceSensorBase):
    """Timestamp of the last successful pipeline turn."""

    _attr_native_value = None
    entity_description = SensorEntityDescription(
        key="last_pipeline_success_at",
        name="Last pipeline success",
        icon="mdi:check-circle-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
    )


class WyomingSatelliteLastErrorSensor(_WyomingSatelliteDeviceSensorBase):
    """Timestamp of the last pipeline error."""

    _attr_native_value = None
    entity_description = SensorEntityDescription(
        key="last_error_at",
        name="Last error",
        icon="mdi:alert-circle-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


class WyomingSatelliteMicPeakLevelSensor(_WyomingSatelliteDeviceSensorBase):
    """Rolling mic peak level in dBFS (negative is quieter)."""

    _attr_native_value = None
    entity_description = SensorEntityDescription(
        key="mic_peak_dbfs",
        name="Mic peak",
        icon="mdi:microphone-plus",
        native_unit_of_measurement="dBFS",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


class WyomingSatelliteMicRmsLevelSensor(_WyomingSatelliteDeviceSensorBase):
    """Rolling mic RMS level in dBFS (negative is quieter)."""

    _attr_native_value = None
    entity_description = SensorEntityDescription(
        key="mic_rms_dbfs",
        name="Mic RMS",
        icon="mdi:microphone",
        native_unit_of_measurement="dBFS",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
