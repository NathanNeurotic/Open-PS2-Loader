RiptOPL bug-report build, {version}
{underline}

Use this build when RiptOPL will not start, stops on a black screen or freezes in the menu. It is
the same RiptOPL as this release, built by the {flavour} toolchain with the field diagnostics on:

- Start-up trace. From the first line of the program up to the video setup, each start-up step is
  printed on screen as a numbered line. If the screen stops changing, the last line is where it
  stopped. The steps after the video setup are covered by the stage colours instead.
- Stage colours. From the video setup on, a start-up that never reaches the menu turns the screen
  one colour for 5 seconds: red (boot folder, memory cards, pad driver), yellow (settings file),
  blue (video, language, theme), cyan (menu setup), white (controller wait), grey (loading the
  settings) or purple (intro, device start-up).
- Freeze and crash reports. If the menu stops drawing for 8 seconds (20 while starting, 60 during
  the intro screen), the screen turns magenta and RIPTOPL-FREEZE.TXT is written to mc0: (mc1: if
  that fails). Give it that long before you restart, or no report is written. A crash turns the
  screen dark red and writes RIPTOPL-CRASH.TXT the same way. Green afterwards means the file was
  written; orange means neither memory card took it.

The ELF is not compressed, and its program starts 0x80 bytes into the file like a standard ps2sdk
build. That is the layout of a test build that started from uLaunchELF on an MMCE where the
compressed build showed a black screen; this build has not been tried on that console yet, so if it
does not start for you either, say so when you report.

How to use it
-------------
1. Copy RIPTOPL-BUGREPORT.ELF next to your normal RIPTOPL.ELF (for example to mc0:/APP_RIPTOPL/ or
   mmce0:/APP_RIPTOPL/). Keep your normal ELF. Settings, game lists and art are shared.
2. Launch RIPTOPL-BUGREPORT.ELF the way you normally launch RiptOPL. A launcher that browses files
   (uLaunchELF, wLaunchELF) can open it directly. A launcher with a fixed entry (OSDMenu, FMCB,
   PS2BBL) keeps starting RIPTOPL.ELF until you point its entry at RIPTOPL-BUGREPORT.ELF or add one.
3. Do what went wrong before.

What to send
------------
- If it stops while starting: a photo of the screen, showing the numbered lines or the colour.
- RIPTOPL-FREEZE.TXT or RIPTOPL-CRASH.TXT from the memory card, if one was written.
- DIAG.TXT, if you can reach the menu: open Drive Status in the main menu and choose Save
  Diagnostics. It goes in the folder RiptOPL keeps its settings in, which Drive Status shows. With
  Debug on in the settings, a launch from an MMCE also saves DIAG.TXT just before the game starts,
  unless the settings folder is on a memory card or an MMCE.
- The version above, how you launch RiptOPL, the device your games are on and what you saw.

Attach them to an issue at {issues} or send them where you asked for help.
