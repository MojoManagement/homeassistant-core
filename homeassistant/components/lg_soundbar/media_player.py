"""Support for LG soundbars."""

from typing import Any, override

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import LGSoundbarClient
from .const import CONF_MODEL, DOMAIN, EQUALISERS, FUNCTIONS
from .models import LGSoundbarCapabilities, capabilities_for_model

EQUIVALENT_FUNCTIONS = (
    ("Optical/HDMI ARC", "E-ARC", "ARC", "LG Optical", "Optical", "Optical2"),
    ("HDMI", "HDMI2", "HDMI3"),
    ("USB", "USB2"),
    ("Bluetooth", "Portable"),
    ("Wi-Fi", "Chromecast", "Spotify"),
)

_BASE_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
)


def _offered_equivalent(function: str, offered: list[int]) -> str | None:
    """Return an offered function from the same group as the given one."""
    group = next((names for names in EQUIVALENT_FUNCTIONS if function in names), ())
    return next((name for name in group if FUNCTIONS.index(name) in offered), None)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up media_player from a config entry."""
    async_add_entities([LGDevice(config_entry)])


class LGDevice(MediaPlayerEntity):
    """Representation of an LG soundbar device."""

    _attr_should_poll = False
    _attr_state = None
    _attr_available = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the LG soundbar."""
        self._config_entry = config_entry
        self._host = config_entry.data[CONF_HOST]
        self._port = config_entry.data[CONF_PORT]
        self._attr_unique_id = config_entry.unique_id or config_entry.entry_id
        self._model: str | None = config_entry.data.get(CONF_MODEL)
        self._capabilities: LGSoundbarCapabilities = capabilities_for_model(self._model)

        self._volume = 0
        self._volume_min = 0
        self._volume_max = 0
        self._function = -1
        self._functions: list[int] = []
        self._equaliser = -1
        self._equalisers: list[int] = []
        self._mute = False
        self._rear_volume = 0
        self._rear_volume_min = 0
        self._rear_volume_max = 0
        self._woofer_volume = 0
        self._woofer_volume_min = 0
        self._woofer_volume_max = 0
        self._bass = 0
        self._treble = 0
        self._support_play_control = False
        self._device_on: bool | None = None
        self._has_powerstatus = False
        self._last_b_connect: bool | None = None
        self._synced_power_cycle = False
        self._stream_type = 0
        self._attr_device_info = self._device_info()

        self._client = LGSoundbarClient(
            self._host,
            self._port,
            self._handle_event,
            self._handle_connection_state,
        )

    def _device_info(self) -> DeviceInfo:
        """Build device registry information from currently known metadata."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="LG",
            model=self._model,
            name=self._host,
        )

    @property
    @override
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return controls supported by the current device profile."""
        features = _BASE_FEATURES
        if self._capabilities.local_power_on:
            features |= MediaPlayerEntityFeature.TURN_ON
        if self._capabilities.local_power_off:
            features |= MediaPlayerEntityFeature.TURN_OFF
        return features

    @override
    async def async_added_to_hass(self) -> None:
        """Open the passive connection after the entity is added."""
        await self._client.async_connect()
        self._attr_available = self._client.connected

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Close the client when the entity is removed."""
        await self._client.async_close()

    async def _handle_connection_state(self, available: bool) -> None:
        """Update network availability without inferring physical power state."""
        self._attr_available = available
        self.async_write_ha_state()

    async def _handle_event(self, response: dict[str, Any]) -> None:
        """Handle encrypted responses and passive device notifications."""
        msg = response.get("msg")
        data = response.get("data") or {}

        if msg == "PRODUCT_INFO":
            await self._update_product_info(data)
        elif msg == "EQ_VIEW_INFO":
            self._update_equalisers(data)
        elif msg == "SPK_LIST_VIEW_INFO":
            await self._update_speaker_info(data)
        elif msg == "FUNC_VIEW_INFO":
            await self._update_function_info(data)
        elif msg == "SETTING_VIEW_INFO":
            self._update_settings(data)
        elif msg == "PLAY_INFO":
            self._update_playinfo(data)

        self.async_write_ha_state()

    async def _update_product_info(self, data: dict[str, Any]) -> None:
        """Learn model metadata only while the soundbar is already active."""
        model = data.get("s_model_name")
        if not isinstance(model, str) or not model:
            return

        if model != self._model:
            self._model = model
            self._capabilities = capabilities_for_model(model)
            self._attr_device_info = self._device_info()
            if self._config_entry.data.get(CONF_MODEL) != model:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data={**self._config_entry.data, CONF_MODEL: model},
                )

        if (
            not self._has_powerstatus
            and self._capabilities.power_state_from_connect
            and self._last_b_connect is not None
        ):
            await self._set_power_state(self._last_b_connect)

    async def _update_speaker_info(self, data: dict[str, Any]) -> None:
        """Update speaker-level information."""
        if "i_vol" in data:
            self._volume = data["i_vol"]
        if "i_vol_min" in data:
            self._volume_min = data["i_vol_min"]
        if "i_vol_max" in data:
            self._volume_max = data["i_vol_max"]
        if "b_mute" in data:
            self._mute = data["b_mute"]
        if "i_curr_func" in data:
            self._function = data["i_curr_func"]
        if "s_user_name" in data:
            self._attr_name = data["s_user_name"]
        if "b_powerstatus" in data:
            self._has_powerstatus = True
            await self._set_power_state(bool(data["b_powerstatus"]))

    async def _update_function_info(self, data: dict[str, Any]) -> None:
        """Update current input and passive connection/power signal."""
        if "i_curr_func" in data:
            self._function = data["i_curr_func"]
        if "ai_func_list" in data:
            self._functions = data["ai_func_list"]
        if "b_connect" not in data:
            return

        connected = bool(data["b_connect"])
        self._last_b_connect = connected

        if not connected:
            self._synced_power_cycle = False

        if not self._has_powerstatus and self._capabilities.power_state_from_connect:
            await self._set_power_state(connected)
            return

        # An unknown model may not trust b_connect as a power signal yet, but a
        # true value is sufficient evidence that issuing metadata GETs cannot
        # wake a device that is currently in standby.
        if connected:
            await self._async_sync_when_awake()

    def _update_settings(self, data: dict[str, Any]) -> None:
        """Update settings reported by the soundbar."""
        if "i_rear_min" in data:
            self._rear_volume_min = data["i_rear_min"]
        if "i_rear_max" in data:
            self._rear_volume_max = data["i_rear_max"]
        if "i_rear_level" in data:
            self._rear_volume = data["i_rear_level"]
        if "i_woofer_min" in data:
            self._woofer_volume_min = data["i_woofer_min"]
        if "i_woofer_max" in data:
            self._woofer_volume_max = data["i_woofer_max"]
        if "i_woofer_level" in data:
            self._woofer_volume = data["i_woofer_level"]
        if "i_curr_eq" in data:
            self._equaliser = data["i_curr_eq"]
        if "s_user_name" in data:
            self._attr_name = data["s_user_name"]

    async def _set_power_state(self, is_on: bool) -> None:
        """Apply an authoritative or model-approved power signal."""
        self._device_on = is_on
        if not is_on:
            self._attr_state = MediaPlayerState.OFF
            self._synced_power_cycle = False
            return

        if self._stream_type == 0 or self._attr_state in (None, MediaPlayerState.OFF):
            self._attr_state = MediaPlayerState.ON
        await self._async_sync_when_awake()

    async def _async_sync_when_awake(self) -> None:
        """Synchronize once per active power cycle, never from standby startup."""
        if self._synced_power_cycle:
            return
        self._synced_power_cycle = True

        if self._model is None:
            await self._client.async_get("PRODUCT_INFO")
        for message in (
            "SPK_LIST_VIEW_INFO",
            "FUNC_VIEW_INFO",
            "EQ_VIEW_INFO",
            "SETTING_VIEW_INFO",
            "PLAY_INFO",
        ):
            await self._client.async_get(message)

    def _update_equalisers(self, data: dict[str, Any]) -> None:
        """Update the equalisers."""
        if "i_bass" in data:
            self._bass = data["i_bass"]
        if "i_treble" in data:
            self._treble = data["i_treble"]
        if "ai_eq_list" in data:
            self._equalisers = data["ai_eq_list"]
        if "i_curr_eq" in data:
            self._equaliser = data["i_curr_eq"]

    def _update_playinfo(self, data: dict[str, Any]) -> None:
        """Update the player info without issuing follow-up polling requests."""
        if "i_stream_type" in data:
            self._stream_type = data["i_stream_type"]
            if self._stream_type == 0:
                self._attr_media_image_url = None
                self._attr_media_artist = None
                self._attr_media_title = None
                if self._device_on is True:
                    self._attr_state = MediaPlayerState.ON
                elif self._device_on is False:
                    self._attr_state = MediaPlayerState.OFF
        if "i_play_ctrl" in data and self._device_on is True and self._stream_type != 0:
            if data["i_play_ctrl"] == 0:
                self._attr_state = MediaPlayerState.PLAYING
            else:
                self._attr_state = MediaPlayerState.PAUSED
        if "s_albumart" in data:
            self._attr_media_image_url = data["s_albumart"].strip() or None
        if "s_artist" in data:
            self._attr_media_artist = data["s_artist"].strip() or None
        if "s_title" in data:
            self._attr_media_title = data["s_title"].strip() or None
        if "b_support_play_ctrl" in data:
            self._support_play_control = data["b_support_play_ctrl"]

    @property
    @override
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if self._volume_max != 0:
            return self._volume / self._volume_max
        return 0

    @property
    @override
    def is_volume_muted(self):
        """Return whether volume is muted."""
        return self._mute

    @property
    @override
    def sound_mode(self):
        """Return the current sound mode."""
        if self._equaliser == -1 or self._equaliser >= len(EQUALISERS):
            return None
        return EQUALISERS[self._equaliser]

    @property
    @override
    def sound_mode_list(self):
        """Return available sound modes."""
        return sorted(
            EQUALISERS[equaliser]
            for equaliser in self._equalisers
            if equaliser < len(EQUALISERS)
        )

    @property
    @override
    def source(self):
        """Return the current input source."""
        if self._function == -1 or self._function >= len(FUNCTIONS):
            return None
        function = FUNCTIONS[self._function]
        if self._function in self._functions:
            return function
        return _offered_equivalent(function, self._functions) or function

    @property
    @override
    def source_list(self):
        """List available input sources."""
        return sorted(
            FUNCTIONS[function]
            for function in self._functions
            if function < len(FUNCTIONS)
        )

    @override
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        if self._volume_max == 0:
            return
        await self._client.async_set(
            "SPK_LIST_VIEW_INFO", {"i_vol": int(volume * self._volume_max)}
        )

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the soundbar."""
        await self._client.async_set("SPK_LIST_VIEW_INFO", {"b_mute": mute})

    @override
    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        await self._client.async_set(
            "FUNC_VIEW_INFO", {"i_curr_func": FUNCTIONS.index(source)}
        )

    @override
    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Set sound mode."""
        await self._client.async_set(
            "EQ_VIEW_INFO", {"i_curr_eq": EQUALISERS.index(sound_mode)}
        )

    @override
    async def async_turn_on(self) -> None:
        """Wake the soundbar using the proven local power-on command."""
        if self._capabilities.local_power_on:
            await self._client.async_set(
                "SPK_LIST_VIEW_INFO", {"b_powerkey": True}
            )

    @override
    async def async_turn_off(self) -> None:
        """Turn off models for which the legacy local command is supported."""
        if self._capabilities.local_power_off:
            await self._client.async_set(
                "SPK_LIST_VIEW_INFO", {"b_powerkey": False}
            )

    @override
    async def async_media_play(self) -> None:
        """Send play command."""
        if self._support_play_control:
            await self._client.async_set("PLAY_INFO", {"i_play_ctrl": 0})

    @override
    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self._support_play_control:
            await self._client.async_set("PLAY_INFO", {"i_play_ctrl": 1})

    async def async_media_play_pause(self) -> None:
        """Send play/pause command."""
        if self.state == MediaPlayerState.PLAYING:
            await self.async_media_pause()
        else:
            await self.async_media_play()
