4d-plugin-udp
=============

Listens to UDP packet broadcast by 4D Server.

##Platform

| carbon | cocoa | win32 | win64 |
|:------:|:-----:|:---------:|:---------:|
|🆗|🚫|🆗|🆗|

Commands
---

```c
// --- Client
UDP_GET_SERVER_LIST
```

Usage
-----
UDP GET SERVER LIST (addresses; hosts; names; port; duration)

addresses (ARRAY)

IPv4 addresses of 4D Servers.

hosts (ARRAY)

Computer names of 4D Servers.

names (ARRAY)

Publish names of 4D Servers.

port (LONGINT)

Port number to listen, default is 19813.

duration (LONGINT)

Number of seconds to listen, default is 1.
