Thank you for sending the log! It showed exactly where Neutrino stops, and it led us to a second problem.

**What was wrong:** the UDPFS network driver had a bug. When a file read from your PC had an odd size, its last byte arrived wrong. Your `neutrino` folder on mc1 has 29 files damaged exactly this way. One of them is a settings file Neutrino needs for network games, so Neutrino stops before the game starts and your PS2 goes back to the browser. You didn't do anything wrong.

**What to do:**
1. On your PC, copy the `neutrino` folder from the RiptOPL zip you downloaded to a USB drive.
2. On your PS2, copy that `neutrino` folder from the USB drive to mc1 (wLaunchELF works for this) and let it replace the old one.
3. For now, don't copy it straight from the PC share over the network. That can damage the files again.

**The UDPFS side:** the next RiptOPL build fixes the network driver, so files RiptOPL reads over UDPFS arrive complete. That may also be why some of your covers didn't show on UDPFS.

Let me know if your games start after you copy the folder again.
