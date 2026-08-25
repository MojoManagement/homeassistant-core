"""Config flow to configure the LG Soundbar integration."""

import asyncio
from typing import override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_PORT, DOMAIN

DATA_SCHEMA = {
    vol.Required(CONF_HOST): str,
}

CONNECT_TIMEOUT = 10


async def async_test_connect(host: str, port: int) -> None:
    """Validate TCP reachability without sending LG application data."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            _reader, writer = await asyncio.open_connection(host, port)
    except (OSError, TimeoutError) as err:
        raise ConnectionError(f"Cannot connect to LG soundbar at {host}:{port}") from err

    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


class LGSoundbarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LG soundbars."""

    VERSION = 1

    @override
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        if user_input is None:
            return self._show_form()

        info = {
            CONF_HOST: user_input[CONF_HOST],
            CONF_PORT: DEFAULT_PORT,
        }
        self._async_abort_entries_match(info)

        errors = {}
        try:
            await async_test_connect(info[CONF_HOST], info[CONF_PORT])
        except (ConnectionError, OSError, TimeoutError):
            errors["base"] = "cannot_connect"
        else:
            return self.async_create_entry(title=info[CONF_HOST], data=info)

        return self._show_form(errors)

    def _show_form(self, errors=None):
        """Show the configuration form."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(DATA_SCHEMA),
            errors=errors or {},
        )
