# LG Soundbar Passive Push Design

## Goal

Fix the Home Assistant `lg_soundbar` integration so LG SP11RA/DSP11RA-class devices are not woken by Home Assistant startup or reconnects, while preserving useful control and reporting accurate power state from passive device notifications.

## Confirmed device behavior

The design is grounded in direct tests against an LG SP11RA on TCP port 9741:

- Opening a TCP connection and sending zero application bytes does not wake the soundbar.
- Valid GET requests such as `PRODUCT_INFO`, `SPK_LIST_VIEW_INFO`, `FUNC_VIEW_INFO`, `EQ_VIEW_INFO`, `SETTING_VIEW_INFO`, and `PLAY_INFO` wake the soundbar from standby.
- The soundbar emits unsolicited plaintext JSON notifications on the same TCP stream, including `FUNC_VIEW_INFO` with `b_connect=true` when active and `b_connect=false` when entering standby.
- Unsolicited volume and mute updates arrive as plaintext `SPK_LIST_VIEW_INFO` notifications.
- Plaintext JSON messages may be concatenated directly, e.g. `{...}{...}`.
- Explicit request/response traffic continues to use the existing `0x10` + big-endian length + AES-256-CBC framing.
- `b_powerkey=true` wakes an SP11RA from standby.
- `b_powerkey=false` does not turn an active SP11RA off.
- Sending `b_powerkey=true` to an already-active SP11RA is a no-op, so the field is not a toggle on this model.

## Current root causes

The existing integration wakes compatible standby devices through two independent startup paths:

1. `async_setup_entry()` calls `test_connect()`, which sends `SPK_LIST_VIEW_INFO`, `MAC_INFO_DEV`, and, when needed, `PRODUCT_INFO`.
2. `media_player.LGDevice._connect()` sends `PRODUCT_INFO`, `MAC_INFO_DEV`, and the full `update()` GET burst.

The integration also defaults the media-player state to `ON` when no `b_powerstatus` has been received and always advertises both `TURN_ON` and `TURN_OFF`.

The `temescal==0.5` transport only understands encrypted `0x10` frames, uses blocking sockets/threads, and ignores the SP11RA plaintext notification stream. It therefore cannot provide the passive state updates needed for a wake-safe implementation.

## Scope

### In scope

- Remove active LG protocol requests from Home Assistant startup and passive reconnect paths.
- Replace the integration's use of `temescal` with a small asyncio-native client owned by the integration.
- Parse both encrypted framed messages and unsolicited plaintext JSON from one TCP byte stream.
- Use passive `b_connect` notifications as the SP11RA/DSP11RA active/standby state signal.
- Keep `b_powerstatus` support for devices that provide it.
- Synchronize full device state only after the device is known to be active.
- Preserve existing volume, mute, source, sound-mode, play, and pause behavior where supported.
- Keep local power-on support via `b_powerkey=true`.
- Do not advertise a nonfunctional local power-off feature for SP11RA/DSP11RA.
- Make the config flow connection test wake-safe.
- Add regression tests for startup, reconnect, parsing, power state, and SP11RA power capabilities.

### Out of scope for this change

- Discovering or implementing a new SP11RA LAN power-off command.
- HDMI-CEC, IR, or external-entity power-off providers.
- Adding new `number` or `switch` platforms for channel levels and advanced settings.
- Firmware reverse engineering.
- General refactoring of unrelated Home Assistant media-player code.

## Architecture

### `client.py`

Own an asyncio TCP connection to the soundbar. The client must support:

- `async_connect()` that opens TCP port 9741 without sending application data.
- a long-running reader task that dispatches decoded messages to a callback.
- `async_send_packet()` for explicit encrypted SET/GET commands.
- reconnect after connection loss with bounded backoff; reconnect itself sends no LG protocol request.
- explicit close/cancellation during integration unload.

The connection layer must not implement polling or protocol heartbeats.

### `protocol.py`

Own packet encoding, encryption/decryption, and incremental stream parsing.

The parser maintains a byte buffer and repeatedly consumes exactly one message at a time:

- If the next byte is `0x10`, wait for the complete five-byte header, read the 4-byte big-endian encrypted payload length, wait for that many bytes, decrypt AES-256-CBC, remove PKCS#7 padding, parse JSON, and emit one message.
- If the next non-whitespace byte is `{`, decode exactly one UTF-8 JSON object using incremental/raw JSON decoding, consume only the bytes belonging to that object, and continue parsing any following object.
- Partial encrypted frames and partial plaintext JSON remain buffered until more bytes arrive.
- Multiple concatenated plaintext JSON objects are emitted independently.
- Mixed encrypted and plaintext messages in one TCP receive buffer are supported.
- Unexpected bytes are treated as protocol errors and must not cause arbitrary requests to be sent to the device.

The existing protocol constants remain compatible with the known LG format:

- IV: `'%^Ur7gy$~t+f)%@`
- key: `T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k`

### `models.py`

Keep device-specific behavior explicit instead of assuming every LG soundbar implements identical power semantics.

Initial profile rules:

- SP11RA/DSP11RA: power on supported, local protocol power off unsupported, active/standby state may be derived from `b_connect` when `b_powerstatus` is absent.
- Other models: retain existing `b_powerstatus` behavior and existing power-off support unless evidence indicates otherwise.

Unknown models must retain existing functionality as far as possible; they must not be silently classified as SP11RA solely because `b_powerstatus` has not yet arrived.

### Home Assistant entity state

Power state is tri-state internally: `True`, `False`, or unknown.

Priority when handling notifications:

1. If `b_powerstatus` is present, use it as the authoritative power signal.
2. For a model profile that explicitly enables `b_connect` power-state mapping, use `b_connect` when `b_powerstatus` is absent.
3. Otherwise leave power state unknown rather than defaulting to `ON`.

Network availability and soundbar power state are separate concepts. An SP11RA may be network-reachable on port 9741 while its media-player state is `OFF`.

### Awake-only synchronization

Startup and reconnect never send GET requests.

When the integration observes a transition to active state (`b_connect=true` or an authoritative `b_powerstatus=true`), it may perform one state synchronization for that power cycle:

- `SPK_LIST_VIEW_INFO`
- `FUNC_VIEW_INFO`
- `EQ_VIEW_INFO`
- `SETTING_VIEW_INFO`
- `PLAY_INFO`

Product metadata requests such as `PRODUCT_INFO` should only be sent while the device is already active and only when required metadata is not already known/cached.

When the device enters standby, the per-power-cycle synchronization marker resets so the next genuine wake can synchronize again.

### Commands and confirmation

Existing SET commands remain encrypted LG protocol requests.

For SP11RA/DSP11RA power-on, send `{"cmd":"set","data":{"b_powerkey":true},"msg":"SPK_LIST_VIEW_INFO"}` and do not optimistically set HA state to `ON`; wait for passive device state confirmation.

For SP11RA/DSP11RA, `TURN_OFF` is not advertised until a functional local off command exists. Other models may retain existing `b_powerkey=false` behavior.

Volume, mute, source, sound-mode, play, and pause commands should prefer device notifications as confirmation rather than immediately issuing follow-up GET requests.

## Config flow

The current config flow actively queries the soundbar to obtain name and UUID and therefore can wake a sleeping device.

The wake-safe flow must validate reachability using only a TCP connect/close to port 9741. It must not send LG protocol data during initial configuration.

For a newly configured device that has not yet exposed metadata, use host-based config entry identity/title initially. Metadata may be learned and cached after the first natural active cycle. Existing entries with UUIDs must continue to load without creating duplicates.

## Manifest

Remove the `temescal==0.5` runtime requirement once all integration code no longer imports it. Change `iot_class` from `local_polling` to `local_push` only when the implementation is fully push-driven and no periodic polling remains.

## Error handling

- Connection loss marks transport availability false but must not infer a physical power transition by itself.
- Reconnect uses bounded backoff and sends zero LG application bytes.
- Malformed packets are logged at an appropriate diagnostic level and discarded/resynchronized without sending corrective protocol traffic.
- A failed SET command must not cause an optimistic state change.
- Async reader tasks must be cancelled and sockets closed on unload.

## Backward compatibility

The change must preserve the existing entity and config-entry domain (`lg_soundbar`). Existing configured entries remain valid.

For devices that expose `b_powerstatus`, that field remains authoritative. Existing source equivalence mapping and supported controls are preserved unless tests demonstrate incompatibility.

SP11RA/DSP11RA behavior is added through explicit capability/model handling rather than changing all LG devices to `b_connect` power semantics.

## Tests

Add focused tests covering:

- integration setup performs no LG protocol request before an active notification;
- reconnect performs no LG protocol request;
- config-flow connectivity validation performs TCP connect only;
- single plaintext JSON event;
- fragmented plaintext JSON event;
- two concatenated plaintext JSON events;
- encrypted frame parsing;
- fragmented encrypted frame parsing;
- mixed encrypted/plaintext stream parsing;
- `b_powerstatus` remains authoritative where present;
- SP11RA `b_connect=true` reports `ON`;
- SP11RA `b_connect=false` reports `OFF`;
- unknown power remains unknown instead of defaulting to `ON`;
- SP11RA exposes `TURN_ON` but not `TURN_OFF`;
- SP11RA `turn_on` sends `b_powerkey=true`;
- first active transition triggers exactly one state synchronization per power cycle;
- standby transition re-arms the next active synchronization;
- passive volume, mute, and source notifications update the entity without polling.

## Acceptance criteria

On a real SP11RA:

1. With the soundbar in standby, restarting Home Assistant does not wake it.
2. Turning the soundbar on externally causes Home Assistant to report `ON` without a standby poll.
3. Turning the soundbar off externally causes Home Assistant to report `OFF` from the passive notification.
4. Volume, mute, and source changes made outside Home Assistant are reflected through passive notifications.
5. Home Assistant `Turn on` wakes the soundbar locally.
6. Home Assistant does not present a knowingly nonfunctional SP11RA local `Turn off` control.
7. Existing supported LG soundbar behavior covered by the current test suite remains passing.
