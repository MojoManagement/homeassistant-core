"""Async client for LG soundbars using TCP port 9741."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import inspect
import logging
from typing import Any

from .protocol import LGSoundbarProtocolError, LGSoundbarStreamParser, encode_packet

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
ConnectionCallback = Callable[[bool], Awaitable[None] | None]

_DEFAULT_RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)


class LGSoundbarClient:
    """Maintain a wake-safe asynchronous connection to an LG soundbar."""

    def __init__(
        self,
        host: str,
        port: int,
        message_callback: MessageCallback,
        connection_callback: ConnectionCallback | None = None,
        *,
        reconnect_delays: Sequence[float] = _DEFAULT_RECONNECT_DELAYS,
    ) -> None:
        self.host = host
        self.port = port
        self._message_callback = message_callback
        self._connection_callback = connection_callback
        self._reconnect_delays = tuple(reconnect_delays) or (1.0,)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._closing = False
        self._available = False

    @property
    def connected(self) -> bool:
        """Return whether a TCP transport is currently connected."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        """Start the wake-safe connection and reconnect loop."""
        self._closing = False
        try:
            await self._open_connection()
        except OSError:
            pass
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(
                self._reader_loop(), name=f"lg_soundbar_{self.host}"
            )

    async def async_close(self) -> None:
        """Stop reconnecting and close the TCP transport."""
        self._closing = True
        task = self._reader_task
        self._reader_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._close_writer()
        await self._set_available(False)

    async def async_send_packet(self, message: dict[str, Any]) -> None:
        """Send one encrypted LG protocol message."""
        if not self.connected:
            await self._open_connection()
            if self._reader_task is None or self._reader_task.done():
                self._reader_task = asyncio.create_task(
                    self._reader_loop(), name=f"lg_soundbar_{self.host}"
                )
        packet = encode_packet(message)
        async with self._send_lock:
            writer = self._writer
            if writer is None or writer.is_closing():
                raise ConnectionError("LG soundbar is not connected")
            writer.write(packet)
            await writer.drain()

    async def async_get(self, message: str) -> None:
        """Request one LG view/info message."""
        await self.async_send_packet({"cmd": "get", "msg": message})

    async def async_set(self, message: str, data: dict[str, Any]) -> None:
        """Set fields in one LG message category."""
        await self.async_send_packet({"cmd": "set", "data": data, "msg": message})

    async def _open_connection(self) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            reader, writer = await asyncio.open_connection(self.host, self.port)
            self._reader = reader
            self._writer = writer
            await self._set_available(True)

    async def _reader_loop(self) -> None:
        parser = LGSoundbarStreamParser()
        reconnect_attempt = 0
        while not self._closing:
            if not self.connected:
                delay = self._reconnect_delays[
                    min(reconnect_attempt, len(self._reconnect_delays) - 1)
                ]
                await asyncio.sleep(delay)
                if self._closing:
                    break
                try:
                    await self._open_connection()
                except OSError:
                    reconnect_attempt += 1
                    continue
                reconnect_attempt = 0
                parser = LGSoundbarStreamParser()

            reader = self._reader
            if reader is None:
                continue
            try:
                data = await reader.read(4096)
            except (ConnectionError, OSError):
                data = b""
            if not data:
                await self._mark_disconnected()
                continue

            try:
                messages = parser.feed(data)
            except LGSoundbarProtocolError as err:
                _LOGGER.debug("Discarding malformed LG soundbar protocol data: %s", err)
                parser = LGSoundbarStreamParser()
                continue

            for message in messages:
                await self._invoke_callback(self._message_callback, message)

    async def _mark_disconnected(self) -> None:
        await self._close_writer()
        await self._set_available(False)

    async def _close_writer(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    async def _set_available(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        if self._connection_callback is not None:
            await self._invoke_callback(self._connection_callback, available)

    @staticmethod
    async def _invoke_callback(callback: Callable[..., Any], *args: Any) -> None:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result
