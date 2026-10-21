Good news: I found the problem and the fix is merged. No more tests needed from you, thank you for your patience!

**What was wrong:** before each UDPFS game, RiptOPL updates a small Neutrino settings file on your memory card (`neutrino/config/bsd-udpfs.toml`). On a memory card, that update could leave a few broken characters at the end of the file. After that, Neutrino could not read the file, so every game went back to the PS2 browser. This was a RiptOPL bug, not something you did.

**What you need to do:** just update RiptOPL to **v1.2.0 Beta 4102 or newer** (the normal rolling download). Nothing else.

The new version repairs the broken file on your memory card by itself the first time you start a game. You don't need to delete or copy anything, and you can keep Neutrino on mc1 like you have it now.

If a game still goes back to the browser after updating, please tell me here.
