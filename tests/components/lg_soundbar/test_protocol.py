"""Tests for LG soundbar wire protocol parsing."""

from homeassistant.components.lg_soundbar.protocol import (
    LGSoundbarStreamParser,
    encode_packet,
)


def test_plaintext_single_event() -> None:
    parser = LGSoundbarStreamParser()
    event = b'{"msg":"FUNC_VIEW_INFO","data":{"b_connect":true}}'
    assert parser.feed(event) == [
        {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": True}}
    ]


def test_plaintext_fragmented_event() -> None:
    parser = LGSoundbarStreamParser()
    assert parser.feed(b'{"msg":"FUNC_VIEW_') == []
    assert parser.feed(b'INFO","data":{"b_connect":false}}') == [
        {"msg": "FUNC_VIEW_INFO", "data": {"b_connect": False}}
    ]


def test_plaintext_concatenated_events() -> None:
    parser = LGSoundbarStreamParser()
    payload = (
        b'{"msg":"SPK_LIST_VIEW_INFO","data":{"i_vol":6}}'
        b'{"msg":"SPK_LIST_VIEW_INFO","data":{"i_vol":7}}'
    )
    assert parser.feed(payload) == [
        {"msg": "SPK_LIST_VIEW_INFO", "data": {"i_vol": 6}},
        {"msg": "SPK_LIST_VIEW_INFO", "data": {"i_vol": 7}},
    ]


def test_encrypted_frame_round_trip() -> None:
    message = {"cmd": "get", "msg": "PRODUCT_INFO"}
    parser = LGSoundbarStreamParser()
    assert parser.feed(encode_packet(message)) == [message]


def test_encrypted_frame_fragmented() -> None:
    message = {"cmd": "set", "msg": "SPK_LIST_VIEW_INFO", "data": {"i_vol": 12}}
    packet = encode_packet(message)
    parser = LGSoundbarStreamParser()
    assert parser.feed(packet[:3]) == []
    assert parser.feed(packet[3:10]) == []
    assert parser.feed(packet[10:]) == [message]


def test_mixed_encrypted_and_plaintext_stream() -> None:
    encrypted = {"cmd": "get", "msg": "EQ_VIEW_INFO"}
    pushed = {"cmd": "notibyset", "msg": "FUNC_VIEW_INFO", "data": {"b_connect": True}}
    payload = encode_packet(encrypted) + b"  " + (
        b'{"cmd":"notibyset","msg":"FUNC_VIEW_INFO","data":{"b_connect":true}}'
    )
    parser = LGSoundbarStreamParser()
    assert parser.feed(payload) == [encrypted, pushed]


def test_utf8_plaintext_event_can_be_fragmented_mid_character() -> None:
    parser = LGSoundbarStreamParser()
    payload = '{"msg":"SETTING_VIEW_INFO","data":{"s_user_name":"Küche"}}'.encode()
    marker = payload.index("ü".encode()) + 1
    assert parser.feed(payload[:marker]) == []
    assert parser.feed(payload[marker:]) == [
        {"msg": "SETTING_VIEW_INFO", "data": {"s_user_name": "Küche"}}
    ]
