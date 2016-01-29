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

Examples
---

```
If (True)
UDP GET SERVER LIST ($p1;$p2;$p3)
Else 
$wait:=1
$port:=19813
UDP GET SERVER LIST ($p1;$p2;$p3;$wait;$port)
End if 
```
