"""Test the lg_soundbar media player."""

import inspect
from unittest.mock import MagicMock, call

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE_LIST,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerEntityFeature,
)
from homeassistant.components.lg_soundbar.const import CONF_MODEL, FUNCTIONS
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from . import find_update_callback, setup_integration

from tests.common import MockConfigEntry

ENTITY_ID = "media_player.127_0_0_1"

AVAILABLE_FUNCTIONS = [
    FUNCTIONS.index("Wi-Fi"),
    FUNCTIONS.index("Bluetooth"),
    FUNCTIONS.index("Optical/HDMI ARC"),
    FUNCTIONS.index("HDMI"),
    FUNCTIONS.index("USB2"),
]


async def send_event(callback, response: dict) -> None:
    """Send a device event through the callback registered with the client."""
    result = callback(response)
    if inspect.isawaitable(result):
        await result


async def send_func_view_info(callback, current_function: str) -> None:
    """Report the given function as the current one via the callback."""
    await send_event(
        callback,
        {
            "msg": "FUNC_VIEW_INFO",
            "data": {
                "i_curr_func": FUNCTIONS.index(current_function),
                "ai_func_list": AVAILABLE_FUNCTIONS,
            },
        },
    )


async def test_setup_sends_no_lg_protocol_requests(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test startup only opens the passive TCP connection."""
    await setup_integration(hass, mock_config_entry)

    instance = mock_client.return_value
    instance.async_connect.assert_awaited_once_with()
    instance.async_get.assert_not_awaited()
    instance.async_set.assert_not_awaited()
    instance.async_send_packet.assert_not_awaited()


async def test_initial_power_state_is_unknown(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the integration does not invent an ON state at startup."""
    await setup_integration(hass, mock_config_entry)

    assert hass.states[ENTITY_ID].state == STATE_UNKNOWN


async def test_sp11ra_b_connect_reports_power_state(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test SP11RA passive b_connect notifications map to ON and OFF."""
    await setup_integration(hass, mock_config_entry)
    callback = find_update_callback(mock_client)

    await send_event(
        callback,
        {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": True, "i_curr_func": 6}},
    )
    assert hass.states[ENTITY_ID].state == STATE_ON

    await send_event(
        callback,
        {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": False, "i_curr_func": 6}},
    )
    assert hass.states[ENTITY_ID].state == STATE_OFF


async def test_powerstatus_stays_authoritative(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test b_connect cannot override a device that exposes b_powerstatus."""
    await setup_integration(hass, mock_config_entry)
    callback = find_update_callback(mock_client)

    await send_event(
        callback,
        {"msg": "SPK_LIST_VIEW_INFO", "data": {"b_powerstatus": False}},
    )
    await send_event(
        callback,
        {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": True}},
    )

    assert hass.states[ENTITY_ID].state == STATE_OFF


async def test_sp11ra_exposes_turn_on_but_not_turn_off(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the known-broken SP11RA local turn-off feature is hidden."""
    await setup_integration(hass, mock_config_entry)

    features = MediaPlayerEntityFeature(
        hass.states[ENTITY_ID].attributes["supported_features"]
    )
    assert MediaPlayerEntityFeature.TURN_ON in features
    assert MediaPlayerEntityFeature.TURN_OFF not in features


async def test_sp11ra_turn_on_sends_wake_command(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test SP11RA turn-on keeps the proven b_powerkey=true command."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        "turn_on",
        {"entity_id": ENTITY_ID},
        blocking=True,
    )

    mock_client.return_value.async_set.assert_awaited_once_with(
        "SPK_LIST_VIEW_INFO", {"b_powerkey": True}
    )


async def test_first_active_transition_syncs_once_per_power_cycle(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test GET synchronization only occurs after a real wake transition."""
    await setup_integration(hass, mock_config_entry)
    instance = mock_client.return_value
    instance.async_get.reset_mock()
    callback = find_update_callback(mock_client)

    active = {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": True}}
    standby = {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": False}}

    await send_event(callback, active)
    assert instance.async_get.await_args_list == [
        call("SPK_LIST_VIEW_INFO"),
        call("FUNC_VIEW_INFO"),
        call("EQ_VIEW_INFO"),
        call("SETTING_VIEW_INFO"),
        call("PLAY_INFO"),
    ]

    await send_event(callback, active)
    assert instance.async_get.await_count == 5

    await send_event(callback, standby)
    await send_event(callback, active)
    assert instance.async_get.await_count == 10


async def test_unknown_model_is_learned_only_after_device_is_active(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test unknown devices may sync metadata after b_connect=true without trusting it yet."""
    data = dict(mock_config_entry.data)
    data.pop(CONF_MODEL)
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title="LG Soundbar",
        data=data,
        unique_id="uuid-unknown-model",
    )
    await setup_integration(hass, entry)
    callback = find_update_callback(mock_client)
    instance = mock_client.return_value
    instance.async_get.reset_mock()

    await send_event(
        callback, {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": True}}
    )
    assert hass.states[ENTITY_ID].state == STATE_UNKNOWN
    assert instance.async_get.await_args_list[0] == call("PRODUCT_INFO")

    await send_event(
        callback, {"msg": "PRODUCT_INFO", "data": {"s_model_name": "SP11RA"}}
    )
    assert hass.states[ENTITY_ID].state == STATE_ON
    assert entry.data[CONF_MODEL] == "SP11RA"


async def test_passive_volume_mute_and_source_updates(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test common external changes update HA directly from push messages."""
    await setup_integration(hass, mock_config_entry)
    callback = find_update_callback(mock_client)

    await send_event(
        callback,
        {
            "msg": "SPK_LIST_VIEW_INFO",
            "data": {"i_vol": 20, "i_vol_min": 0, "i_vol_max": 40, "b_mute": True},
        },
    )
    await send_func_view_info(callback, "Bluetooth")

    state = hass.states[ENTITY_ID]
    assert state.attributes["volume_level"] == 0.5
    assert state.attributes["is_volume_muted"] is True
    assert state.attributes["source"] == "Bluetooth"


async def test_source_falls_back_to_available_equivalent(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reported-but-unoffered source falls back to an offered equivalent."""
    await setup_integration(hass, mock_config_entry)
    callback = find_update_callback(mock_client)

    await send_func_view_info(callback, "E-ARC")
    assert hass.states[ENTITY_ID].attributes["source"] == "Optical/HDMI ARC"

    await send_func_view_info(callback, "HDMI3")
    assert hass.states[ENTITY_ID].attributes["source"] == "HDMI"


async def test_source_list_only_contains_offered_functions(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the source list remains based on ai_func_list."""
    await setup_integration(hass, mock_config_entry)
    callback = find_update_callback(mock_client)

    await send_func_view_info(callback, "E-ARC")
    assert hass.states[ENTITY_ID].attributes[ATTR_INPUT_SOURCE_LIST] == [
        "Bluetooth",
        "HDMI",
        "Optical/HDMI ARC",
        "USB2",
        "Wi-Fi",
    ]
