"""Common fixtures for the lg_soundbar tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.lg_soundbar.const import (
    CONF_MODEL,
    DEFAULT_PORT,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PORT

from tests.common import MockConfigEntry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked SP11RA config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="LG Soundbar",
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: DEFAULT_PORT,
            CONF_MODEL: "SP11RA",
        },
        unique_id="uuid",
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Mock the async LG soundbar client."""
    with patch(
        "homeassistant.components.lg_soundbar.media_player.LGSoundbarClient",
        autospec=True,
    ) as mock_client:
        instance = mock_client.return_value
        instance.connected = True
        instance.async_connect = AsyncMock()
        instance.async_close = AsyncMock()
        instance.async_get = AsyncMock()
        instance.async_set = AsyncMock()
        instance.async_send_packet = AsyncMock()
        yield mock_client
