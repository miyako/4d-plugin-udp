![version](https://img.shields.io/badge/version-18%2B-EB8E5F)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-32%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-udp)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-udp/total)

# 4d-plugin-udp

The UDP plugin discovers 4D Server instances on the local network by broadcasting a UDP discovery packet and collecting the replies it receives within a time window. It exposes a single command, `UDP Get server list`, which returns a `Collection` of `Object`, one per server that responded.

| Command | Returns | Purpose |
|---|---|---|
| [`UDP Get server list`](#udp-get-server-list) | Collection | Broadcasts a discovery packet and collects replies from 4D Server instances on the local network |

**Platforms:** Windows, macOS. Thread-safe (`threadSafe: true` in the manifest — see [Requirements & platform notes](#requirements--platform-notes)).

---

## Requirements & platform notes

- The command's only parameter is optional — call it with no arguments to use the built-in defaults, or pass an `Object` to override `port` and/or `wait`.
- Discovery is a fixed-length UDP broadcast protocol matching 4D Server's own "4D Server II" beacon. Only devices that reply within the `wait` window, in the exact expected reply format, are included — this is best-effort discovery, not a guaranteed-complete inventory of every server on the network.
- **Only IPv4 discovery is currently active.** The source contains an IPv6 discovery path, but it's compiled out in this build — servers reachable only over IPv6 will not appear in the results.
- No 4D error is raised on failure. If the underlying socket can't be created or configured (e.g. broadcast isn't permitted on the network interface), the command silently returns an empty collection rather than raising an error — check for an empty result rather than expecting an exception.
- The `host` field in each result is passed through as-received and is **not** character-set converted. The `name` field **is** converted (from Shift-JIS or Mac Roman, depending on the database's localization, into UTF-8) — see the per-command description below for why these two text fields can behave differently for non-ASCII values.
- As of this build, malformed or wrong-sized replies (e.g. from something other than a real 4D Server answering on the same port) are silently discarded rather than processed — this is a fix applied during a recent source review; older builds may not have this filtering. If you're on an older build and see garbled entries in the result, this is why.

---

## UDP Get server list

### Syntax

```4d
UDP Get server list ( options ) -> Result
```

| Parameter | Type | Description |
|---|---|---|
| `options` | Object | Optional. Discovery settings — see below. Omit entirely to use both defaults. |
| Result | Collection | One `Object` per server that replied, each with `host`, `addr`, and `name` (see below). |

`options` accepts:

| Property | Type | Description |
|---|---|---|
| `port` | Longint | Optional. UDP port to broadcast the discovery packet on. Defaults to `19813` if omitted or if the value is not a valid port number (finite, `> 0`, `<= 65535`). |
| `wait` | Longint | Optional. How long, in seconds, to keep listening for replies after broadcasting. Defaults to `1` if omitted or if the value is not valid (finite, `> 0`; values above `3600` are clamped to `3600` as of this build). |

Each object in the returned collection has:

| Property | Type | Description |
|---|---|---|
| `host` | Text | The responding server's host name, exactly as sent by the server. Not character-set converted — see Description. |
| `addr` | Text | The responding server's IPv4 address, as a dotted-quad string (e.g. `"192.168.1.42"`). |
| `name` | Text | The responding server's display name, converted to UTF-8 based on the current database's localization (see Description). |

### Description

The command sends a fixed 96-byte UDP broadcast (`255.255.255.255`) built to mimic 4D Server's own discovery beacon, then listens for replies for `wait` seconds before returning whatever it collected.

- **`host` vs. `name` encoding differs.** `host` is copied from the reply as raw bytes with no charset conversion — if a server's host name contains non-ASCII characters, they'll come through as whatever bytes the server sent, not necessarily valid UTF-8. `name`, by contrast, is explicitly converted: the plugin reads the current database's localization via `Get database localization`, and if it's Japanese (`"ja"`), converts `name` from Shift-JIS; otherwise it assumes Mac Roman. Either way, the result is converted to UTF-8 before being placed in the returned object. If your server names use a different source encoding than these two, the conversion will produce incorrect text for `name` specifically (this is a source-level assumption, not something you can override via `options`).
- **Silent failure.** If the socket can't be created, or `SO_BROADCAST` can't be set on it (both platform/network-permission-dependent), the command does not raise a 4D error. You'll get back an empty collection. There's currently no way to distinguish "nothing responded" from "the discovery broadcast itself failed to go out" from the return value alone.
- **`wait` blocks the calling process for up to that many seconds** (the command yields cooperatively via `PA_YieldAbsolute` while waiting, but the command itself doesn't return until the window elapses or, in practice, until the full window has passed — there's no early-return the moment a reply arrives, since it keeps listening for the whole duration). Don't set `wait` to a large value inside a UI-blocking context.
- IPv6 discovery is not currently active (see [Requirements & platform notes](#requirements--platform-notes)); `addr` will always be an IPv4 address in this build.

### Example

From the plugin's own test method (`TEST.4dm`):

```4d
//%attributes = {}
$locale:=Get database localization:C1009(Default localization:K5:21)

$servers:=UDP Get server list (New object:C1471("wait";1;"port";19813))
```

Using the defaults instead of specifying them explicitly:

```4d
// Same effective settings as the example above (port 19813, wait 1 second),
// since both are the built-in defaults.
$servers:=UDP Get server list (New object:C1471)
```

Listing what came back:

```4d
$servers:=UDP Get server list (New object:C1471("wait";2))

For each ($server; $servers)
	ALERT($server.name+" @ "+$server.addr+" ("+$server.host+")")
End for each
```

---

## Error handling & troubleshooting

- **Empty collection, no error.** A failed socket/broadcast setup returns `[]`, not a 4D error — always check whether the collection is empty rather than wrapping the call in error-catching code.
- **Missing servers on an IPv6-only network.** Only IPv4 discovery is active in this build; a server reachable solely via IPv6 will never appear in the results, silently.
- **Garbled `host` text for non-ASCII host names.** `host` isn't charset-converted; if you need reliably readable text for display, prefer `name` (which is converted) and treat `host` as a raw/diagnostic value.
- **Fewer results than expected servers on the network.** Increase `wait` — a `1`-second window (the default) may not be enough time for every server to reply, especially on a busy or larger network. `wait` is capped at `3600` seconds as of this build.
- **Command appears to hang under an unusually large `wait`.** The command blocks for up to `wait` seconds by design; this isn't a defect, but avoid large values in synchronous/UI-blocking call sites.

---

## Quick reference

```4d
// Defaults (port 19813, wait 1s)
$servers:=UDP Get server list (New object:C1471)

// Custom port/wait
$servers:=UDP Get server list (New object:C1471("port";19813;"wait";2))

// Iterate results
For each ($server; $servers)
	// $server.host, $server.addr, $server.name
End for each
```
