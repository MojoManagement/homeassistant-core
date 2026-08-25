"""Tests for the asyncio LG soundbar client."""

import asyncio

import pytest

from homeassistant.components.lg_soundbar.client import LGSoundbarClient


@pytest.mark.asyncio
async def test_connect_sends_zero_application_bytes() -> None:
    connected = asyncio.Event()
    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connected.set()
        try:
            received.append(await asyncio.wait_for(reader.read(1), 0.1))
        except TimeoutError:
            received.append(b"")
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = LGSoundbarClient("127.0.0.1", port, lambda message: None)
    try:
        await client.async_connect()
        await asyncio.wait_for(connected.wait(), 1)
        await asyncio.sleep(0.15)
        assert received == [b""]
    finally:
        await client.async_close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_reader_dispatches_plaintext_notification() -> None:
    got_message: asyncio.Future[dict] = asyncio.get_running_loop().create_future()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b'{"msg":"FUNC_VIEW_INFO","data":{"b_connect":true}}')
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    def callback(message: dict) -> None:
        if not got_message.done():
            got_message.set_result(message)

    client = LGSoundbarClient("127.0.0.1", port, callback)
    try:
        await client.async_connect()
        assert await asyncio.wait_for(got_message, 1) == {
            "msg": "FUNC_VIEW_INFO",
            "data": {"b_connect": True},
        }
    finally:
        await client.async_close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_reconnect_sends_zero_application_bytes() -> None:
    connection_count = 0
    second_connected = asyncio.Event()
    received_on_second: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connection_count
        connection_count += 1
        if connection_count == 1:
            writer.close()
            await writer.wait_closed()
            return
        second_connected.set()
        try:
            received_on_second.append(await asyncio.wait_for(reader.read(1), 0.1))
        except TimeoutError:
            received_on_second.append(b"")
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = LGSoundbarClient(
        "127.0.0.1", port, lambda message: None, reconnect_delays=(0.01,)
    )
    try:
        await client.async_connect()
        await asyncio.wait_for(second_connected.wait(), 1)
        await asyncio.sleep(0.15)
        assert connection_count >= 2
        assert received_on_second == [b""]
    finally:
        await client.async_close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_initial_connection_failure_reconnects_silently(monkeypatch) -> None:
    attempts = 0
    second_connected = asyncio.Event()
    received: list[bytes] = []
    real_open_connection = asyncio.open_connection

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        second_connected.set()
        try:
            received.append(await asyncio.wait_for(reader.read(1), 0.1))
        except TimeoutError:
            received.append(b"")
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def flaky_open_connection(host: str, target_port: int):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("offline")
        return await real_open_connection(host, target_port)

    monkeypatch.setattr(asyncio, "open_connection", flaky_open_connection)
    client = LGSoundbarClient(
        "127.0.0.1", port, lambda message: None, reconnect_delays=(0.01,)
    )
    try:
        await client.async_connect()
        await asyncio.wait_for(second_connected.wait(), 1)
        await asyncio.sleep(0.15)
        assert attempts >= 2
        assert received == [b""]
    finally:
        await client.async_close()
        server.close()
        await server.wait_closed()
