"""The Wyoming integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.components.wyoming import (
    DomainDataItem,
    WyomingService,
    async_register_websocket_api,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .client import AsyncTcpClient
from .const import ATTR_SPEAKER, DOMAIN
from .custom import CustomActions, CustomEvent
from .devices import VASatelliteDevice

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

SATELLITE_PLATFORMS = [
    Platform.ASSIST_SATELLITE,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SENSOR,
]

__all__ = [
    "ATTR_SPEAKER",
    "DOMAIN",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]


class WyomingError(HomeAssistantError):
    """Base class for Wyoming errors."""


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Wyoming integration."""
    async_register_websocket_api(hass)

    async def _handle_get_logs(call) -> None:
        """Request an on-demand log pull from one or more satellites."""
        device_ids = call.data.get("device_id") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        matched = 0
        for entry_item in hass.data.get(DOMAIN, {}).values():
            device = getattr(entry_item, "device", None)
            if device is None:
                continue
            if device_ids and device.device_id not in device_ids:
                continue
            device.send_custom_action(CustomActions.GET_LOGS)
            matched += 1

        if not matched:
            _LOGGER.warning(
                "vaca.get_logs: no matching satellite found (device_id=%s)",
                device_ids or "<all>",
            )

    hass.services.async_register(
        DOMAIN,
        "get_logs",
        _handle_get_logs,
    )

    async def _handle_reset_pipeline(call) -> None:
        """Ask one or more satellites to reset their pipeline state."""
        device_ids = call.data.get("device_id") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        matched = 0
        for entry_item in hass.data.get(DOMAIN, {}).values():
            device = getattr(entry_item, "device", None)
            if device is None:
                continue
            if device_ids and device.device_id not in device_ids:
                continue
            device.send_custom_action(CustomActions.RESET_PIPELINE)
            matched += 1

        if not matched:
            _LOGGER.warning(
                "vaca.reset_pipeline: no matching satellite found (device_id=%s)",
                device_ids or "<all>",
            )

    hass.services.async_register(
        DOMAIN,
        "reset_pipeline",
        _handle_reset_pipeline,
    )

    async def _handle_audio_selftest(call) -> None:
        """Kick off an on-device audio loopback self-test."""
        device_ids = call.data.get("device_id") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        matched = 0
        for entry_item in hass.data.get(DOMAIN, {}).values():
            device = getattr(entry_item, "device", None)
            if device is None:
                continue
            if device_ids and device.device_id not in device_ids:
                continue
            device.send_custom_action(CustomActions.AUDIO_SELFTEST)
            matched += 1

        if not matched:
            _LOGGER.warning(
                "vaca.audio_selftest: no matching satellite found (device_id=%s)",
                device_ids or "<all>",
            )

    hass.services.async_register(
        DOMAIN,
        "audio_selftest",
        _handle_audio_selftest,
    )

    async def _handle_navigate(call) -> None:
        """Navigate satellite webview to a dashboard path."""
        device_id = call.data.get("device_id")
        path = call.data.get("path", "")
        for entry_id, item in hass.data.get(DOMAIN, {}).items():
            if hasattr(item, "device") and item.device is not None:
                device = item.device
                if device.device_id == device_id or device_id is None:
                    device.send_custom_action(
                        CustomActions.NAVIGATE, json.dumps({"path": path})
                    )
                    return
        _LOGGER.warning(
            "vaca.navigate: no matching satellite found (device_id=%s)",
            device_id,
        )

    hass.services.async_register(
        DOMAIN,
        "navigate",
        _handle_navigate,
    )

    # ── Multi-device wake arbitration ──────────────────────────────────
    # When multiple satellites hear the wake word simultaneously, we pick
    # the one with the highest mic level (closest to the speaker) and
    # send stand-down to the others.
    _wake_events: dict[str, dict] = {}
    _wake_timer_handle: asyncio.TimerHandle | None = None
    ARBITRATION_WINDOW_S = 0.5  # 500ms collection window

    def _resolve_wake_arbitration(_now=None):
        nonlocal _wake_timer_handle
        _wake_timer_handle = None
        if len(_wake_events) <= 1:
            # Only one device heard the wake — no arbitration needed.
            _wake_events.clear()
            return

        # Pick the device with the highest mic peak (least negative dBFS)
        winner = max(_wake_events.items(), key=lambda x: x[1].get("mic_peak_dbfs", -120))
        winner_id = winner[0]
        _LOGGER.info(
            "Wake arbitration: %d devices heard wake. Winner: %s (peak=%.1f dBFS)",
            len(_wake_events), winner_id, winner[1].get("mic_peak_dbfs", -120),
        )

        # Send stand-down to losers
        for device_id, wake_data in _wake_events.items():
            if device_id == winner_id:
                continue
            _LOGGER.info("Sending stand-down to %s (peak=%.1f dBFS)", device_id, wake_data.get("mic_peak_dbfs", -120))
            for entry_item in hass.data.get(DOMAIN, {}).values():
                device = getattr(entry_item, "device", None)
                if device is not None and device.device_id == device_id:
                    device.send_custom_action(CustomActions.STAND_DOWN)
                    break

        _wake_events.clear()

    async def _handle_wake_detected(event):
        nonlocal _wake_timer_handle
        data = event.data
        device_id = data.get("device_id")
        if not device_id:
            return

        _wake_events[device_id] = data

        # Reset the arbitration timer
        if _wake_timer_handle is not None:
            _wake_timer_handle.cancel()
        _wake_timer_handle = hass.loop.call_later(
            ARBITRATION_WINDOW_S, _resolve_wake_arbitration
        )

    hass.bus.async_listen("vaca_wake_detected", _handle_wake_detected)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load Wyoming."""
    service = await WyomingService.create(entry.data["host"], entry.data["port"])

    if service is None:
        raise ConfigEntryNotReady("Unable to connect")

    item = DomainDataItem(service=service)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = item

    await hass.config_entries.async_forward_entry_setups(entry, service.platforms)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    if (satellite_info := service.info.satellite) is not None:
        # Create satellite device
        dev_reg = dr.async_get(hass)

        # Use config entry id since only one satellite per entry is supported
        satellite_id = entry.entry_id
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, satellite_id)},
            name=satellite_info.name,
            suggested_area=satellite_info.area,
        )

        item.device = VASatelliteDevice(
            satellite_id=satellite_id,
            device_id=device.id,
        )
        item.device.capabilities = await get_device_capabilities(item)

        # Set up satellite entity, sensors, switches, etc.
        await hass.config_entries.async_forward_entry_setups(entry, SATELLITE_PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Wyoming."""
    item: DomainDataItem = hass.data[DOMAIN][entry.entry_id]

    platforms = list(item.service.platforms)
    if item.device is not None:
        platforms += SATELLITE_PLATFORMS

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        del hass.data[DOMAIN][entry.entry_id]

    return unload_ok


async def get_device_capabilities(item: DomainDataItem):
    """Get device capabilities."""
    capabilities: dict[str, Any] | None = None

    for _ in range(4):
        try:
            async with (
                AsyncTcpClient(item.service.host, item.service.port) as client,
                asyncio.timeout(1),
            ):
                # Describe -> Info
                await client.write_event(CustomEvent("capabilities").event())
                while True:
                    event = await client.read_event()
                    if event is None:
                        raise WyomingError(  # noqa: TRY301
                            "Connection closed unexpectedly",
                        )

                    if CustomEvent.is_type(event.type) and (
                        event_data := CustomEvent.from_event(event).event_data
                    ):
                        capabilities = event_data.get("capabilities")
                        break  # while

                if capabilities is not None:
                    break  # for
        except (TimeoutError, OSError, WyomingError) as ex:
            _LOGGER.warning(
                "Error getting device capabilities: %s, %s", ex, capabilities
            )
            # Sleep and try again
            await asyncio.sleep(2)

    return capabilities
