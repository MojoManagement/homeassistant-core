"""Test the lg_soundbar config flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.components.lg_soundbar.config_flow import async_test_connect
from homeassistant.components.lg_soundbar.const import DEFAULT_PORT, DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


async def test_connect_only_opens_and_closes_tcp() -> None:
    """Test connectivity validation sends no LG application data."""
    reader = MagicMock()
    writer = MagicMock()
    writer.wait_closed = AsyncMock()

    with patch(
        "homeassistant.components.lg_soundbar.config_flow.asyncio.open_connection",
        new=AsyncMock(return_value=(reader, writer)),
    ) as open_connection:
        await async_test_connect("1.1.1.1", DEFAULT_PORT)

    open_connection.assert_awaited_once_with("1.1.1.1", DEFAULT_PORT)
    writer.write.assert_not_called()
    writer.close.assert_called_once_with()
    writer.wait_closed.assert_awaited_once_with()


async def test_form(hass: HomeAssistant) -> None:
    """Test a reachable soundbar can be configured without querying it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with (
        patch(
            "homeassistant.components.lg_soundbar.config_flow.async_test_connect",
            new_callable=AsyncMock,
        ) as test_connect,
        patch(
            "homeassistant.components.lg_soundbar.async_setup_entry", return_value=True
        ) as mock_setup_entry,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "1.1.1.1"}
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "1.1.1.1"
    assert result2["result"].unique_id is None
    assert result2["data"] == {
        CONF_HOST: "1.1.1.1",
        CONF_PORT: DEFAULT_PORT,
    }
    test_connect.assert_awaited_once_with("1.1.1.1", DEFAULT_PORT)
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_host_already_configured(hass: HomeAssistant) -> None:
    """Test a host cannot be configured twice without waking it."""
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.1.1.1", CONF_PORT: DEFAULT_PORT},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.lg_soundbar.config_flow.async_test_connect",
        new_callable=AsyncMock,
    ) as test_connect:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "1.1.1.1"}
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
    test_connect.assert_not_awaited()


async def test_form_os_error(hass: HomeAssistant) -> None:
    """Test connection errors are reported."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.lg_soundbar.config_flow.async_test_connect",
        new=AsyncMock(side_effect=OSError),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "1.1.1.1"}
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_timeout(hass: HomeAssistant) -> None:
    """Test connection timeouts are reported."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.lg_soundbar.config_flow.async_test_connect",
        new=AsyncMock(side_effect=asyncio.TimeoutError),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "1.1.1.1"}
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}
