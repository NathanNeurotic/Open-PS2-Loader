# Tales of Rebirth: investigation checkpoint for #285 / #1246

This is separate from the optional console i.LINK ID feature.

Confirmed report evidence: an indirect Discord screenshot transcription says Tales of Rebirth ENG v1.0 fails on an unspecified latest nightly and works with an unspecified grimdoomer OPL build. No later reproduction details were present in GitHub comments at inspection.

Missing: failing and working ELF hashes/builds, selected core, storage backend, translated-image hash/patch provenance, failure stage, console model and active configuration. No identified reproduction image or reporter environment was supplied for this task. No reproduction or meaningful good/bad revision pair is established.

Source inspection separates native launch settings built in sbPrepare and each backend from Neutrino's external runtime/argument path. Merged i.LINK retry/attachment work changes storage transport, whereas sceCdRI returns console identity; the naming overlap establishes no causal link. Held Tales of the Abyss break/streaming PRs concern a different game and remain held.

Next step: identify the exact build/core/backend and image, then compare the same image/configuration on known-good and failing builds from one history. Bisect only that demonstrated interval. A divergent fork is a comparison, not an endpoint for a linear bisect. Record boot stage, output and image/ELF hashes for each run.

No speculative delay, timing change or title-specific patch was added. The ID override does not establish that this report is fixed. Keep both issues open pending reproduction and reporter acceptance.

- https://github.com/NathanNeurotic/RiptOPL/issues/285
- https://github.com/NathanNeurotic/Open-PS2-Loader/issues/1246

