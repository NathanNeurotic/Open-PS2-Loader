# PC CARD CF driver

Adapted from mihhru/PS2CF 1.0, commit 9b6ed3702b59a87512426952e003125a5b4f0e3c.
Original component notices and PS2SDK AFL-2.0 license are retained. PS2CF's OPL
integration is distributed under OPL's AFL-3.0. No FMCB images or mymc tooling
are included here.

RiptOPL changes: opt-in menu initialization, explicit DEV9 bus ownership,
no GUI takeover of a powered card, and loader-owned game handoff only.
The game variant rejects writes. Hardware behavior in RiptOPL is unverified.
