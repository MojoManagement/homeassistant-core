"""LG soundbar wire protocol helpers."""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_HEADER_MAGIC = 0x10
_HEADER_SIZE = 5
_BLOCK_SIZE_BITS = 128
_MAX_ENCRYPTED_PAYLOAD = 1024 * 1024
_IV = b"'%^Ur7gy$~t+f)%@"
_KEY = b"T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k"
_JSON_DECODER = json.JSONDecoder()


class LGSoundbarProtocolError(ValueError):
    """Raised when a complete LG protocol message is invalid."""


def _encrypt(payload: bytes) -> bytes:
    padder = padding.PKCS7(_BLOCK_SIZE_BITS).padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_KEY), modes.CBC(_IV)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt(payload: bytes) -> bytes:
    if not payload or len(payload) % 16:
        raise LGSoundbarProtocolError("Encrypted payload is not AES block aligned")
    decryptor = Cipher(algorithms.AES(_KEY), modes.CBC(_IV)).decryptor()
    padded = decryptor.update(payload) + decryptor.finalize()
    unpadder = padding.PKCS7(_BLOCK_SIZE_BITS).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as err:
        raise LGSoundbarProtocolError("Invalid encrypted payload padding") from err


def encode_packet(message: dict[str, Any]) -> bytes:
    """Encode one LG JSON request in the encrypted TCP frame format."""
    plaintext = json.dumps(message, separators=(",", ":")).encode()
    encrypted = _encrypt(plaintext)
    return bytes((_HEADER_MAGIC,)) + len(encrypted).to_bytes(4, "big") + encrypted


class LGSoundbarStreamParser:
    """Incrementally parse encrypted frames and plaintext JSON notifications."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        """Feed bytes into the parser and return all complete decoded messages."""
        self._buffer.extend(data)
        messages: list[dict[str, Any]] = []

        while self._buffer:
            self._discard_leading_whitespace()
            if not self._buffer:
                break

            if self._buffer[0] == _HEADER_MAGIC:
                message = self._consume_encrypted_frame()
                if message is None:
                    break
                messages.append(message)
                continue

            if self._buffer[0] == ord("{"):
                result = self._consume_plaintext_json()
                if result is None:
                    break
                messages.append(result)
                continue

            self._resynchronize()

        return messages

    def _discard_leading_whitespace(self) -> None:
        consumed = 0
        for value in self._buffer:
            if value not in b" \t\r\n":
                break
            consumed += 1
        if consumed:
            del self._buffer[:consumed]

    def _consume_encrypted_frame(self) -> dict[str, Any] | None:
        if len(self._buffer) < _HEADER_SIZE:
            return None

        length = int.from_bytes(self._buffer[1:5], "big")
        if length <= 0 or length > _MAX_ENCRYPTED_PAYLOAD or length % 16:
            del self._buffer[0]
            raise LGSoundbarProtocolError(f"Invalid encrypted payload length: {length}")

        frame_size = _HEADER_SIZE + length
        if len(self._buffer) < frame_size:
            return None

        encrypted = bytes(self._buffer[_HEADER_SIZE:frame_size])
        del self._buffer[:frame_size]
        plaintext = _decrypt(encrypted)
        try:
            message = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise LGSoundbarProtocolError("Invalid encrypted JSON payload") from err
        if not isinstance(message, dict):
            raise LGSoundbarProtocolError("LG protocol JSON payload is not an object")
        return message

    def _consume_plaintext_json(self) -> dict[str, Any] | None:
        try:
            text = bytes(self._buffer).decode("utf-8")
        except UnicodeDecodeError as err:
            if err.reason == "unexpected end of data":
                return None
            raise LGSoundbarProtocolError("Invalid UTF-8 in plaintext notification") from err

        try:
            message, char_end = _JSON_DECODER.raw_decode(text)
        except json.JSONDecodeError as err:
            if self._plaintext_may_be_incomplete(err, text):
                return None
            raise LGSoundbarProtocolError("Invalid plaintext JSON notification") from err

        if not isinstance(message, dict):
            raise LGSoundbarProtocolError("LG plaintext JSON payload is not an object")
        byte_end = len(text[:char_end].encode("utf-8"))
        del self._buffer[:byte_end]
        return message

    @staticmethod
    def _plaintext_may_be_incomplete(error: json.JSONDecodeError, text: str) -> bool:
        if error.pos >= len(text) - 1:
            return True
        return error.msg.startswith("Unterminated string") or not text.rstrip().endswith("}")

    def _resynchronize(self) -> None:
        next_frame = self._buffer.find(bytes((_HEADER_MAGIC,)), 1)
        next_json = self._buffer.find(b"{", 1)
        candidates = [idx for idx in (next_frame, next_json) if idx != -1]
        if not candidates:
            self._buffer.clear()
            return
        del self._buffer[: min(candidates)]
