# ShanWan 2563:0575 controller evidence

The USB driver recognizes VID:PID `2563:0575` as an input-only generic HID pad.
The legacy `SHANWAN_PS3_PID` constant remains for source compatibility; its name
does not establish that the reported device is a PS3 controller.

Contributor freergam3r describes the tested unit as a wireless PS2-style pad with
an **ANALOG mode button**, rather than a PS/Home button. Their October 31, 2026
clarification says their work started from a fresh ps2homebrew/OPL checkout.
Their reported PAL 90K menu/game results apply to that build. They are not
acceptance evidence for our integration or every device sharing this VID/PID.
Real DS3/DS4 regression testing was planned, not reported complete.

Contributed source: [Fgr-35 snapshot a901ec6](https://github.com/Fgr-35/Modified-drivers-for-usb-controller-in-opl/tree/a901ec6ac5b7a04bbb554698a48804854ec70f9a).

## Current interpretation and unresolved behavior

Menu USB input and PADEMU use the same `translate_pad_shanwan` helper. It interprets
seven bytes without a report ID. It writes the canonical DS2 payload order:
button low/high, right X/Y, left X/Y. Current input bytes 5/6 feed right X/Y and
3/4 feed left X/Y. These are parser labels, pending report captures from both
ANALOG modes on the reporter's unit.

The contributed PADEMU assignments serialize the same byte pairs. Some of its
comments label the output pairs differently, and its menu path uses another
header arrangement. Those comments and offsets alone do not justify swapping
our axes. The contributor also reports menu-stick neutralization in their own
polling workaround and remaining menu-axis differences, while games work for
them. This does not establish that our menu-navigation issue is resolved.

No PS/Home input is established for this unit. PADEMU therefore keeps the
existing zero PS-button argument to `padMacroPerform`. Treat the ANALOG button
as a mode transition until raw reports establish a safe interpretation.

## Evidence needed before a runtime remap

- Capture descriptor information and raw reports at rest, with one axis/button
  at a time, in both ANALOG modes and while switching modes.
- Include short/failed transfers, reconnects and simultaneous USB storage.
- Replay those captures through the real shared translator and verify serialized
  DS2 output. Then verify menu RPC and in-game PADEMU separately on the console.
- Check coexistence with native pads and real DS3/DS4 controllers.

This clarification changes comments and documentation only. It makes no runtime
axis, polling, output or macro change and claims no physical-console acceptance.
