# LG Soundbar Passive Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Home Assistant `lg_soundbar` integration wake-safe and push-driven for SP11RA/DSP11RA while preserving existing behavior for older LG soundbars.

**Architecture:** Replace the integration-local dependency on blocking `temescal` transport behavior with an asyncio client and hybrid stream parser that understands both encrypted `0x10` frames and unsolicited plaintext JSON notifications. Home Assistant connects silently, learns active/standby state from device notifications, synchronizes only after a genuine wake, and advertises power capabilities per model profile.

**Tech Stack:** Python, asyncio streams, PyCryptodome AES-CBC, Home Assistant entity/config-flow APIs, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-lg-soundbar-passive-push-design.md`

## Global Constraints

- Home Assistant startup and passive reconnect must send zero LG application bytes while the soundbar may be in standby.
- `b_powerstatus` stays authoritative where present.
- `b_connect` is a power-state signal only for explicit SP11RA/DSP11RA profiles.
- SP11RA/DSP11RA expose local TURN_ON but not local TURN_OFF.
- No polling or protocol heartbeat is introduced.
- Existing `lg_soundbar` config entries remain valid.
- No HDMI-CEC/IR/external power-off provider in this change.

---

### Task 1: Add hybrid protocol parser

**Files:**
- Create: `homeassistant/components/lg_soundbar/protocol.py`
- Create: `tests/components/lg_soundbar/test_protocol.py`

**Interfaces:**
- Produces `encode_packet(message: dict[str, Any]) -> bytes`.
- Produces `LGSoundbarStreamParser.feed(data: bytes) -> list[dict[str, Any]]`.

- [ ] Write failing tests for single plaintext JSON, fragmented plaintext JSON, concatenated JSON objects, encrypted frame, fragmented encrypted frame, and mixed encrypted/plaintext buffers.
- [ ] Run `pytest -q tests/components/lg_soundbar/test_protocol.py` and verify failures are due to missing parser implementation.
- [ ] Implement AES-CBC encode/decode and incremental mixed-stream parsing with exact byte consumption.
- [ ] Re-run `pytest -q tests/components/lg_soundbar/test_protocol.py` and require all parser tests to pass.

### Task 2: Add asyncio client with silent connect/reconnect

**Files:**
- Create: `homeassistant/components/lg_soundbar/client.py`
- Create: `tests/components/lg_soundbar/test_client.py`

**Interfaces:**
- Produces `LGSoundbarClient(host, port, message_callback, connection_callback=None)`.
- Produces `async_connect()`, `async_close()`, `async_send_packet(message)`, and explicit GET/SET helpers used by the entity.
- Consumes `LGSoundbarStreamParser` and `encode_packet` from Task 1.

- [ ] Write failing tests proving `async_connect()` writes zero bytes, the reader dispatches parsed events, and reconnect itself writes zero bytes.
- [ ] Run `pytest -q tests/components/lg_soundbar/test_client.py` and verify expected failures.
- [ ] Implement asyncio stream connection, reader task, bounded reconnect backoff, send lock, and clean shutdown without polling/heartbeats.
- [ ] Re-run `pytest -q tests/components/lg_soundbar/test_client.py` and require all client tests to pass.

### Task 3: Make setup/config flow wake-safe

**Files:**
- Modify: `homeassistant/components/lg_soundbar/__init__.py`
- Modify: `homeassistant/components/lg_soundbar/config_flow.py`
- Modify: `tests/components/lg_soundbar/test_config_flow.py`
- Modify: `tests/components/lg_soundbar/conftest.py`

**Interfaces:**
- `async_test_connect(host: str, port: int) -> None` validates TCP reachability only.
- Config flow initially uses host-based identity/title when metadata is unavailable.

- [ ] Write failing tests proving setup and config flow perform only TCP connect/close and send no LG requests.
- [ ] Run the focused config-flow/setup tests and verify expected failures.
- [ ] Replace active `temescal` discovery with wake-safe TCP connectivity validation.
- [ ] Preserve loading of existing UUID-backed entries and prevent host duplicates for new entries.
- [ ] Re-run focused tests and require them to pass.

### Task 4: Add model capability profiles and passive power state

**Files:**
- Create: `homeassistant/components/lg_soundbar/models.py`
- Modify: `homeassistant/components/lg_soundbar/media_player.py`
- Modify: `tests/components/lg_soundbar/test_media_player.py`

**Interfaces:**
- Produces immutable model capabilities with `local_power_on`, `local_power_off`, and `power_state_from_connect`.
- `b_powerstatus` overrides `b_connect` whenever both are available.

- [ ] Write failing tests for unknown initial state, SP11RA/DSP11RA `b_connect` ON/OFF, authoritative `b_powerstatus`, SP11RA TURN_ON without TURN_OFF, and correct `b_powerkey=true` command.
- [ ] Run focused media-player tests and verify expected failures.
- [ ] Integrate the asyncio client into the entity, remove default-ON behavior, and apply explicit model profiles.
- [ ] Re-run focused tests and require them to pass.

### Task 5: Add awake-only synchronization and passive media updates

**Files:**
- Modify: `homeassistant/components/lg_soundbar/media_player.py`
- Modify: `tests/components/lg_soundbar/test_media_player.py`

**Interfaces:**
- One synchronization burst per active power cycle.
- Standby resets the synchronization marker.
- Passive volume/mute/source notifications update HA without polling.

- [ ] Write failing tests that startup sends no GETs, first active transition triggers exactly one sync, repeated active events do not resync, standby re-arms sync, and passive volume/mute/source update entity state.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement transition-aware awake-only synchronization and event-driven state updates.
- [ ] Re-run focused tests and require them to pass.

### Task 6: Remove temescal dependency and update manifest

**Files:**
- Modify: `homeassistant/components/lg_soundbar/manifest.json`
- Modify: remaining `lg_soundbar` imports/tests as needed.

**Interfaces:**
- Integration contains no runtime import of `temescal`.
- Manifest uses `iot_class: local_push` and has no `temescal==0.5` requirement.

- [ ] Add/adjust tests that fail if the integration still depends on mocked temescal behavior.
- [ ] Remove all integration runtime `temescal` imports and replace static function/equalizer mappings with local constants preserving current names/IDs.
- [ ] Update manifest to `local_push` and remove temescal requirement.
- [ ] Run all `tests/components/lg_soundbar` tests and require zero failures.

### Task 7: Full verification and review

**Files:**
- Review all changed integration/test files.

- [ ] Run `pytest -q tests/components/lg_soundbar` and capture exact pass/fail output.
- [ ] Run relevant lint/type/format checks available in the Home Assistant checkout for changed files.
- [ ] Run `git diff --check`.
- [ ] Inspect `git diff dev...HEAD` for accidental unrelated changes and verify every acceptance criterion that can be automated.
- [ ] Commit only verified changes to `fix/lg-soundbar-passive-push`.
- [ ] Leave real-device acceptance criteria (restart-in-standby, external ON/OFF, volume/mute/source, HA TURN_ON) for the SP11RA hardware test after code verification.
