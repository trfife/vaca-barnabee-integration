"""Select entities for Wyoming integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.assist_pipeline import (
    AssistPipelineSelect,
    VadSensitivity,
    VadSensitivitySelect,
)
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import restore_state
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .devices import VASatelliteDevice
from .entity import VASatelliteEntity

if TYPE_CHECKING:
    from homeassistant.components.wyoming import DomainDataItem

_NOISE_SUPPRESSION_LEVEL: Final = {
    "off": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "max": 4,
}
_DEFAULT_NOISE_SUPPRESSION_LEVEL: Final = "off"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities."""
    item: DomainDataItem = hass.data[DOMAIN][config_entry.entry_id]
    device: VASatelliteDevice = item.device  # type: ignore[assignment]

    # Setup is only forwarded for satellites
    assert item.device is not None

    async_add_entities(
        [
            WyomingSatellitePipelineSelect(hass, device),
            WyomingSatelliteNoiseSuppressionLevelSelect(device),
            WyomingSatelliteVadSensitivitySelect(hass, device),
            WyomingSatelliteWakeWordEngineSelect(device),
            WyomingSatelliteWakeWordSelect(device),
            WyomingSatelliteWakeWordSoundSelect(device),
            WyomingSatelliteScreenTimeoutSelect(device),
            WyomingSatelliteScreenOrientationModeSelect(device),
            WyomingSatelliteScreensaverModeSelect(device),
        ]
    )


class WyomingSatellitePipelineSelect(VASatelliteEntity, AssistPipelineSelect):
    """Pipeline selector for Wyoming satellites."""

    def __init__(self, hass: HomeAssistant, device: VASatelliteDevice) -> None:
        """Initialize a pipeline selector."""
        self.device = device

        VASatelliteEntity.__init__(self, device)
        AssistPipelineSelect.__init__(self, hass, DOMAIN, device.satellite_id)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        await super().async_select_option(option)
        self.device.set_pipeline_name(option)


class WyomingSatelliteNoiseSuppressionLevelSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent noise suppression level setting."""

    entity_description = SelectEntityDescription(
        key="noise_suppression_level",
        translation_key="noise_suppression_level",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = _DEFAULT_NOISE_SUPPRESSION_LEVEL
    _attr_options = list(_NOISE_SUPPRESSION_LEVEL.keys())

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            self._attr_current_option = state.state

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_noise_suppression_level(_NOISE_SUPPRESSION_LEVEL[option])


class WyomingSatelliteVadSensitivitySelect(VASatelliteEntity, VadSensitivitySelect):
    """VAD sensitivity selector for Wyoming satellites."""

    def __init__(self, hass: HomeAssistant, device: VASatelliteDevice) -> None:
        """Initialize a VAD sensitivity selector."""
        self.device = device

        VASatelliteEntity.__init__(self, device)
        VadSensitivitySelect.__init__(self, hass, device.satellite_id)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        await super().async_select_option(option)
        self.device.set_vad_sensitivity(VadSensitivity(option))


class WyomingSatelliteWakeWordSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent wake word setting."""

    entity_description = SelectEntityDescription(
        key="wake_word",
        translation_key="wake_word",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "hey_jarvis"

    @property
    def options(self) -> list[str]:
        """Return the list of available wake word options."""
        options = ["None"]
        options.extend(self.get_wake_word_options())
        return options

    def get_wake_word_options(self) -> list[str]:
        """Return the list of available wake word options."""
        wake_options: list[str] = []
        if self._device.info and self._device.info.wake:
            for wake_program in self._device.info.wake:
                if wake_program.name == "available_wake_words":
                    wake_options = [
                        model.name.replace("_", " ").title()
                        for model in wake_program.models
                        if model.attribution.name in [self._device.wakeword_engine, ""]
                    ]
        return wake_options

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)
        # Default to the first available option if no state is found
        elif self.options:
            await self.async_select_option(self.options[0])

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._device.device_id}_wakewords_update",
                self.test,
            )
        )

    async def test(self, _data: dict[str, Any]) -> None:
        """Test method to trigger state update."""
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_custom_setting("wake_word", option.lower().replace(" ", "_"))


class WyomingSatelliteWakeWordSoundSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent wake word sound setting."""

    entity_description = SelectEntityDescription(
        key="wake_word_sound",
        translation_key="wake_word_sound",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "havpe"
    _attr_options = ["none", "alexa", "havpe", "ding", "bubble"]

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_custom_setting("wake_word_sound", option)


class WyomingSatelliteScreenTimeoutSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent screen timeout setting."""

    entity_description = SelectEntityDescription(
        key="screen_timeout",
        translation_key="screen_timeout",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "60"
    _attr_options = ["15", "30", "60", "120", "300", "600", "1800"]

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_custom_setting(self.entity_description.key, int(option))


class WyomingSatelliteWakeWordEngineSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent wake word engine setting."""

    entity_description = SelectEntityDescription(
        key="wake_word_engine",
        translation_key="wake_word_engine",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "openwakeword"
    _attr_options = ["openwakeword", "microwakeword"]

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)
        else:
            await self.async_select_option(self._attr_current_option)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self._device.wakeword_engine = option

        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_{self._device.device_id}_wakewords_update",
            {"engine": option},
        )

        self.async_write_ha_state()
        self._device.set_custom_setting("wake_word_engine", option)


class WyomingSatelliteScreenOrientationModeSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to represent screen orientation mode setting."""

    entity_description = SelectEntityDescription(
        key="screen_orientation_mode",
        translation_key="screen_orientation_mode",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "auto"
    _attr_options = [
        "auto",
        "portrait",
        "landscape",
        "reverse_portrait",
        "reverse_landscape",
    ]

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_custom_setting("screen_orientation_mode", option)


# All available bg-animation screensaver options from ibz0q/lovelace-bg-animation
SCREENSAVER_MODE_OPTIONS = [
    "slideshow",
    "animation.1.home-assistant-particles",
    "application.1.media-background",
    "generator.1.svg-wave",
    "animation.2.shooting-stars",
    "generator.2.knots",
    "animation.3.spipa-circle",
    "animation.4.colored-swipe",
    "animation.5.neon-hexagon",
    "animation.5.plasma",
    "animation.6.binary-spiral",
    "animation.7.rainbowness",
    "animation.9.rainbow-particles",
    "animation.10.css-dark-particles",
    "animation.11.space",
    "animation.12.gradient-particles",
    "animation.13.cyber-lights",
    "animation.14.ribbons-two",
    "animation.15.sound",
    "animation.16.veil",
    "animation.17.ribbons",
    "animation.18.particle-cube",
    "animation.19.trapped-particles",
    "animation.20.manifold",
    "animation.21.noise-abstraction",
    "animation.22.cloth-ribbons",
    "animation.23.ribbons-four",
    "animation.24.trapped-gradient",
    "animation.25.galactic-swimmers",
    "animation.26.gpu-particles",
    "animation.27.tron",
    "animation.28.black-sand-flow-field-v2",
    "animation.31.blooming-flower",
    "animation.32.canvas-blending-gradient-circles",
    "animation.33.canvas-bokeh",
    "animation.34.canvas-color-teams",
    "animation.35.canvas-light-explosion",
    "animation.36.starfield",
    "animation.46.codevember-05-simplex-vector-flow-field",
    "animation.47.color-trails",
    "animation.48.colorful-wanderers",
    "animation.49.curved-lines",
    "animation.50.sidelined",
    "animation.52.polyhedron-galaxy",
    "animation.53.stars",
    "animation.54.stars-galaxy",
    "animation.56.azimuthal-viscosity",
    "animation.57.browniandrix-noise",
    "animation.58.browniandrix-noise-l3",
    "animation.59.dimension-two-and-a-half",
    "animation.60.digital-frontier",
    "animation.61.cube",
    "animation.62.neural",
    "animation.63.green-circuit",
    "animation.64.howls-moving-castle",
    "animation.65.cristal-lands",
    "animation.66.fog-of-war",
    "animation.67.fly-particle",
    "animation.68.rgb-wave",
    "animation.69.bit-ocean",
    "animation.70.blur",
    "animation.71.interactive-gradient",
    "animation.72.playstation-3-bg-style",
    "animation.73.alien-blackout-intro-scene-react-webgl",
    "animation.74.dvd-screensaver",
    "animation.75.hexagonal-truchet-10-print",
    "animation.76.hexanimation",
    "animation.77.hexanimation-2",
    "animation.78.just-in-case",
    "animation.79.canvas-ribbons",
    "generator.79.more-columns",
    "animation.80.particle-waves",
    "animation.81.remember-windows",
    "animation.82.storm",
    "animation.83.strange-tubes",
    "animation.84.troisjs-starfield",
    "animation.85.truchet-10-print-imitation",
    "generator.86.silky-carpet",
    "animation.87.point-sprites",
    "animation.88.fish-tank",
    "animation.89.shamrocks",
    "animation.90.aurora",
    "animation.91.sliced-blobs",
    "animation.92.aurora-v2",
]


class WyomingSatelliteScreensaverModeSelect(
    VASatelliteEntity, SelectEntity, restore_state.RestoreEntity
):
    """Entity to select screensaver mode (slideshow or bg-animation)."""

    entity_description = SelectEntityDescription(
        key="screensaver_mode",
        translation_key="screensaver_mode",
        icon="mdi:monitor-shimmer",
        entity_category=EntityCategory.CONFIG,
    )
    _attr_should_poll = False
    _attr_current_option = "slideshow"
    _attr_options = SCREENSAVER_MODE_OPTIONS

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state in self.options:
            await self.async_select_option(state.state)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._device.set_custom_setting("screensaver_mode", option)
