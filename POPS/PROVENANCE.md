# POPS package provenance

This register covers every regular file shipped from `POPS/`. Exact byte counts and SHA-256
digests live in `provenance.json`; `.github/scripts/verify_pops_provenance.py` checks the files
offline and rejects missing, unexpected, truncated, or modified payloads.

## POPStarter r13 acquisition

- Project/version: POPStarter r13, 2019/06/05, by krHACKen.
- Official maintainer page: <https://www.psx-place.com/threads/popstarter.19139/>.
- Acquired archive: `POPStarter_20190605.7z`, 2,824,745 bytes, SHA-256
  `77f509d54ac329081b9ff2dcc2979b54ab099f4598d2f362e016034eb03187ed`.
- Retrieved: 2026-09-17T17:19:12Z from the archive URL linked in the official thread:
  <http://ddata.over-blog.com/1/06/19/78/01022202/POPStarter_20190605.7z>. The thread attributes
  that download to the maintainer's AssemblerGames source post. The current PSX-Place attachment
  is Cloudflare-protected, so byte-equivalence between that attachment and this acquired archive
  remains unverified.

The official page states that r13 excludes the Sony emulator and Sony libraries, permits reposting
when it is not repacked with decrypted emulator files or a PlayStation BIOS, and forbids direct
links to the separate Sony POPS binaries in that thread. The archive contains no formal licence
file, so this register records that maintainer statement rather than assigning an SPDX licence.
RiptOPL does not ship `POPS.ELF`, `POPS.PAK`, `POPS_IOX.PAK`, `IOPRP252.IMG`, or a PS1 BIOS.

## Comparison with this repository

The archive's `POPStarter_20190605/POPSTARTER.ELF` is an exact match for
`POPSTARTER VERSIONS/MAIN/POPSTARTER.ELF`. All other shipped launcher roles are derived from that
exact payload using only these zero-indexed configuration bytes:

| role | offset 1040 | offset 1043 | upstream relationship |
|---|---:|---:|---|
| MAIN | `00` | `02` | exact |
| DEBUG | `ff` | `02` | modified from exact upstream |
| USBDELAY | `00` | `06` | modified from exact upstream |
| USBDELAY_DEBUG | `ff` | `06` | modified from exact upstream |
| USBDELAY_LONGER_DEBUG | `ff` | `09` | modified from exact upstream |

The root `POPSTARTER.ELF` is byte-identical to DEBUG. Both paths are retained because one is the
package default and the other is the user-selectable named variant.

`PATCH_5.BIN` and the six legacy network modules (`ps2ip.irx`, `smbman.irx`, `ps2smap.irx`,
`ps2dev9.irx`, `poweroff.irx`, and `SMSUTILS.irx`) are absent from the acquired r13 archive. The
official page distributes network modules separately, but those attachment bytes were not
retrieved during this acquisition. Their origins, upstream relationships, and licence references
therefore remain explicitly `unverified` in the manifest. `PATCH_5.BIN` starts with `PATCH`, but a
bounds-checked strict IPS record walk does not find a valid in-bounds `EOF`; its structure must not
be guessed without upstream tooling or documentation.

The ATA, MMCE, MX4SIO, and USB-exFAT driver rows are exact local mirrors of the files documented in
`modules/bdmassault/PROVENANCE.md`. That document's MMCE caveat still applies: the exact upstream
build source is unpinned. The iLink pair and memory-card icon provenance remain explicit where
unverified.

## Verify checked-in bytes

Run from the repository root:

```sh
python3 .github/scripts/verify_pops_provenance.py
```

This command is deliberately offline. Updating a payload requires updating its manifest entry and
the human-readable relationship above from immutable acquisition evidence; the verifier never
downloads mutable upstream content.
