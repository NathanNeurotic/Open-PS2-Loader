# Notes for ps2sdk

RiptOPL builds or patches several of [ps2sdk](https://github.com/ps2dev/ps2sdk)'s IOP modules instead of
embedding the SDK's prebuilt copies. This page records the ps2sdk defects behind those changes, and the
ones we found and left alone, so that ps2sdk maintainers and anyone else using ps2sdk can act on them.
None of it has been filed with ps2sdk. Use any of it freely.

Every "still in master" below was checked on 2026-10-27 against ps2sdk master
[`329e2bb`](https://github.com/ps2dev/ps2sdk/commit/329e2bb43287e16af16c4dde1c614e2662c24468)
(2026-10-12), which was still master that day.

> [!IMPORTANT]
> Nothing here is tested on a console unless its evidence line says **hardware**.

Each entry gives its evidence:

- **Hardware**: seen on a real console. The entry says who saw it and when.
- **Host test**: the ps2sdk or fork C code, compiled on a PC and run against simulated replies or disks.
  Tests named here are in [`.github/scripts/`](../.github/scripts/) and run in CI. "Review harness" means a
  one-off test from the 2026-10-27 review that is not in the repository.
- **Source**: found by reading the code only.

## Summary

| Module | ps2sdk source | Our copy | Still in master | Fixed in master since our copy | Our own choices |
| --- | --- | --- | --- | --- | --- |
| [smbman](#smbman) | `iop/network/smbman` | [`modules/network/smbman-ra`](../modules/network/smbman-ra/) | 4 | 0 | 1 |
| [usbd (usbd_mini)](#usbd-usbd_mini) | `iop/usb/usbd` | [`modules/usb/usbd-ra`](../modules/usb/usbd-ra/) | 2 | 0 | 0 |
| [ps2ips](#ps2ips) | `iop/tcpip/tcpips` | [`modules/network/ps2ips`](../modules/network/ps2ips/) | 5 | 0 | 0 |
| [atad (ata_bd)](#atad-ata_bd) | `iop/dev9/atad` | [`modules/hdd/atad`](../modules/hdd/atad/) | 3 | 1 | 1 |
| [APA (ps2hdd-osd)](#apa-ps2hdd-osd) | `iop/hdd/apa`, `iop/hdd/libapa` | [`modules/hdd/apa`](../modules/hdd/apa/) | 7 | 0 | 4 |
| [BDM](#bdm) | `iop/fs/bdm`, `iop/fs/libbdm` | [`modules/bdm`](../modules/bdm/) | 9 | 2 | 1 |
| [bdmfs_fatfs](#bdmfs_fatfs) | `iop/fs/bdmfs_fatfs` | patched in CI | 4 | 0 | 1 |
| [IEEE1394_bd](#ieee1394_bd) | `iop/iLink/IEEE1394_bd` | [`modules/ilink/IEEE1394_bd`](../modules/ilink/IEEE1394_bd/) | 10 | 0 | 1 |
| [iLinkman](#ilinkman) | `iop/iLink/iLinkman` | [`modules/ilink/iLinkman`](../modules/ilink/iLinkman/) | 11 | 0 | 0 |

ps2ips and IEEE1394_bd each had one defect of our own, both fixed on 2026-10-27 and listed with the
module. Defects we saw in modules we did not change are under [other ps2sdk modules](#other-ps2sdk-modules).

The smbman [write-count](ps2sdk-patches/0001-smbman-a-write-is-complete-only-for-the-bytes-the-se.patch)
and [write ByteCount](ps2sdk-patches/0002-smbman-send-at-most-65534-bytes-per-WRITE_ANDX-reque.patch)
fixes are ready as ps2sdk patches: they apply in that order to master `329e2bb` with `git am`. For the
rest, our copies are the reference. smbman-ra, usbd-ra, ps2ips and iLinkman diff cleanly against ps2sdk. APA, BDM and IEEE1394_bd
were reformatted with clang-format in a baseline commit that each `ORIGIN.txt` describes, so diff them
against that commit. atad was added already reformatted and changed (`bcac683b`), so diff it against its
pin with whitespace ignored (`diff -w`), or follow its `/* FORK */` markers.

## smbman

Our copy is ps2sdk's `iop/network/smbman` with four changes. ps2sdk has not changed those sources since
`d44e0128` (2024-12-12). Every flavour embeds our copy; before 2026-10-27 only the RetroAchievements
flavour did. Only the menu loads it; in-game SMB access uses OPL's own driver in
`modules/iopcore/cdvdman`.

### A short write is reported as complete

**Still in master.**

- **Where:** `iop/network/smbman/src/smb.c`, `smb_WriteAndX()`, which ends with `return nbytes;`.
- **What goes wrong:** it never reads the WRITE_ANDX response's Count.
  [MS-CIFS 2.2.4.43.2](https://learn.microsoft.com/openspecs/windows_protocols/ms-cifs/43a10562-269f-4536-b460-17b494405cc4)
  lets a server answer a write to a full disk with success and a Count of 0, and a server may store fewer
  bytes than it was sent. In both cases `write()` reports success for bytes the server never stored.
- **Who hits it:** writers to a server that reports a short write with a success status, such as ksmbd's
  SMB1 code (read from source, not run). Samba (read from source), Windows (per MS-CIFS) and PS2-Servers
  (run against a full disk) answer with an error status instead, which smbman already turns into `-EIO`.
- **Our change:** return the server's Count. A reply shorter than 45 bytes, a WordCount under 6, or a
  Count larger than the request is a failed write. `smb_WriteFile()` already sends the rest after a short
  Count. When a later request of the same call gets a zero Count or fails, it now returns the bytes the
  earlier requests stored, instead of 0 or the error, so the caller's file position stays true; the next
  call gets the zero Count or the error.
- **Evidence:** host test
  [`test_smbman_ra_write_count.py`](../.github/scripts/test_smbman_ra_write_count.py). It fails on master's
  `smb.c` and passes with the patch. Not tested on hardware or against a live server that sends a short
  Count.

### A 65535-byte write request says it carries no data

**Still in master.**

- **Where:** `smb.c`. `smb_WriteAndX()` sets `WR->ByteCount = (u16)nbytes + padding`, and
  `smb_WriteFile()` sends up to `CLIENT_MAX_XFER_SIZE` (65535) bytes per request.
- **What goes wrong:** ByteCount is 16 bits and counts the one padding byte as well as the data, so a
  65535-byte request goes out with a ByteCount of 0.
- **Who hits it:** IOP callers writing 65535 bytes or more in one call; EE fileXio callers only after
  raising the RW buffer to at least that size. How servers treat a ByteCount of 0 was not checked.
- **Our change:** send at most 65534 bytes per request (`CLIENT_MAX_WRITE_SIZE`). Reads keep 65535.
- **Evidence:** host test
  [`test_smbman_ra_write_count.py`](../.github/scripts/test_smbman_ra_write_count.py) now requires a
  ByteCount of data plus one on every request and fails with the 65535-byte chunk. Not tested on
  hardware or against a live server.

### A file another session still holds cannot be opened, even to read

**Still in master.**

- **Where:** `smb.c`. `smb_OpenAndX()` goes straight to `smb_NTCreateAndX()` when the server supports NT
  SMBs, and that function turns every status except success and access-denied into `-EIO`.
- **What goes wrong:** a session that died with a file open (a console switched off mid-game; OPL never
  logs off) leaves the server holding the file. The server then refuses NT_CREATE_ANDX with a sharing
  violation, and smbman returns `-EIO`. It never tries the older SMB_COM_OPEN_ANDX, which the server in
  our report still granted.
- **Who hits it:** smbman users reading a file a dead session holds, on such a server. Which server
  software behaves this way is not recorded.
- **Our change:** on `STATUS_SHARING_VIOLATION` (or ERRDOS/ERRbadshare), a read retries with the legacy
  open.
- **Evidence:** hardware: [hacan359](https://github.com/hacan359) on 2026-09-10. Images an earlier run held open
  [hashed correctly](RETROACHIEVEMENTS.md#an-image-an-earlier-run-left-open-on-the-share-can-still-be-hashed).
  The console model, the server software, and whether the build tested was ours or hacan359's own are
  not recorded. No host test. Not tried: asking for a wider NT share mode instead.

### Our choice: a held file opens read-only and reports -EBUSY

Not a ps2sdk defect. An open that writes, creates or truncates does not retry, and a refused open returns
`-EBUSY` instead of `-EIO`, so the menu can say that the file is held. A distinct errno for a sharing
violation could go to ps2sdk on its own; the read-only limit is OPL's choice.

### A password longer than 256 characters overruns a 512-byte buffer

**Still in master.**

- **Where:** `auth.c`, `NTLM_Password_Hash()`. The loop over `strlen(password)` writes into
  `static u8 passwd_buf[512]` with no bound.
- **What goes wrong:** the devctl password fields are 256 bytes. A NUL-terminated field is safe. An
  unterminated one, for example after `strncpy()` from a 256-character source, lets `strlen()` run on and
  the loop write past the buffer. Through `SMB_DEVCTL_GETPASSWORDHASHES` the bytes after the field are
  stale fileXio RPC data, so the write can overrun by about 3.5 KB.
- **Who hits it:** a caller that passes an unterminated 256-byte password. A correct caller cannot, and
  OPL cannot (its password is 32 bytes).
- **Our change:** cap the length at 255. That still reads past the field; a better fix bounds the scan to
  the field: `for (i = 0; i < 256 && password[i]; i++)`.
- **Evidence:** review harness with AddressSanitizer: master writes out of bounds from 257 characters, our
  copy does not. Not tested on hardware.

### Seen in smbman, not changed here

- `STATUS_OBJECT_NAME_NOT_FOUND` is defined but never used, so opening a missing file returns `-EIO`, not
  `-ENOENT`. OPL works around it in its EE code. (Source.)
- `smb_write()`'s check `!(mode & O_RDWR) && !(mode & O_WRONLY)` never rejects a read-only handle. It is
  dead code in practice, because iomanX returns `-EBADF` before calling the driver. (Source.)

## usbd (usbd_mini)

Our copy is ps2sdk's `iop/usb/usbd` at
[`314d87e7`](https://github.com/ps2dev/ps2sdk/commit/314d87e71e298b06b7ec459a97dd0b54a3e0cb5c)
(2024-04-01), built as usbd_mini with byte-identical sources. That is FreeUsbd 0.1.2, the driver before
the rewrite [`b1f7ff96`](https://github.com/ps2dev/ps2sdk/commit/b1f7ff96647e8929acc9643d9b27af3af32c4ad5)
("USBD feature update", authored 2024-09-04, merged on 2024-09-24). The rewrite's real parent is
`2dc6b32f`; our copy lacks three small header changes made in between. Every flavour embeds it, and the
game's IOP loads it again after the game's IOP reboot when the game runs from USB or PADEMU is on.

Our copy exports usbd version 1.1, and current SDK clients import 1.2. ps2sdk's loadcore matches on the
major version only, so they link. Whether the console ROM's loadcore does the same was not checked; a
hardware no-regression run (below) found no problem.

### A game run from USB loses its controller and sound at its first IOP reboot

**Still in master:** master's usbd is still the rewrite.

- **Where:** the rewritten `iop/usb/usbd/src`. No function has been identified.
- **What goes wrong:** with ps2sdk's current usbd_mini, Dynasty Warriors 2 run from USB loses its
  controller and its sound at the game's first IOP reboot. Swapping only usbd_mini back to the
  pre-rewrite driver fixes it. The cause is not isolated.
- **Who hits it:** OPL and other loaders that embed a usbd_mini built after `b1f7ff96`. One title is
  recorded here. ps2sdk [issue #908](https://github.com/ps2dev/ps2sdk/issues/908) reports a different
  symptom with the same fix (Crash Bandicoot: The Wrath of Cortex from USB is very slow to reach its menu,
  then shows a black screen), and [PR #911](https://github.com/ps2dev/ps2sdk/pull/911) proposes restoring
  FreeUsbd for usbd_mini. On 2026-10-27 #908 was open and #911 was not merged.
- **Our change:** we replaced the whole module; nothing inside the rewrite was patched.
- **Evidence:** hardware: [hacan359](https://github.com/hacan359) on 2026-09-10, also with official OPL. The console model and OPL
  version are not recorded. Zack's hardware run on 2026-09-10 is a no-regression check only. No host test.

### The endpoint number is masked with 0x1F

**Still in master.** Latent.

`iop/usb/usbd/src/endpoint.c`, `openDeviceEndpoint()`, builds the OHCI endpoint descriptor with
`(bEndpointAddress & 0x1F) << 7`. The endpoint-number field is 4 bits wide, so bit 4 spills into the
direction field; FreeUsbd masks with `0xF`. USB reserves that bit, so a compliant device never sets it.
This is horizonends's finding, posted on #908 on 2026-08-01. (Source.)

## ps2ips

Our copy is ps2sdk's `iop/tcpip/tcpips/src/ps2ips.c` with five fixes; master has not changed the file
since `8451bd58` (2026-07-09). Four fixes are marked "RA fix" in the source; the DNS fix is unmarked.
Every flavour embeds it, but only the RetroAchievements flavour's own code calls the receive and DNS
paths. The EE side stays ps2sdk's stock libps2ips, which a loader cannot change.

### Every recv() that returns data writes 16 bytes past an EE buffer

**Still in master.**

- **Where:** `do_recv()` and `do_recvfrom()` DMA `sizeof(rests_pkt)`, 144 bytes, to the EE.
  `ee/rpc/tcpips/src/ps2ipc.c` receives them in `static int _intr_data[32]`, 128 bytes.
- **What goes wrong:** bytes 128–143 land on whatever the EE linker placed next. In our RA build that is
  libps2ips's socket operations table (`__ps2ipc_fdman_ops_socket`, defined in
  `ee/rpc/tcpips/src/ps2ipc_ps2sdk.c`), which fits the reported symptom of sockets leaking until
  `socket()` fails (unconfirmed). `fa7359ff` (2018) grew the packet without growing the EE buffer.
- **Who hits it:** every EE program using libps2ips, on every TCP `recv()` that returns data.
- **Our change:** the IRX sends at most 128 bytes, 80 when there is no unaligned tail, so it can return
  only 48 bytes of a receive's unaligned tail. It peeks first and takes only what fits. This is a
  workaround, because the EE library is ps2sdk's; the entry on our own defect below says what its first
  version lost and what it still costs UDP. The ps2sdk fix belongs on the EE side: make `_intr_data` at least `sizeof(rests_pkt)` (144 bytes), rounded
  up to a multiple of 64 bytes and kept 64-byte aligned. Ship it together with the next fix, which
  otherwise starts sending recvfrom's 144 bytes there too.
- **Evidence:** review harness (stock code DMAs 144 bytes) and the symbol layout of our RA build. Not
  tested on hardware.

### UDP recvfrom() never fills the caller's buffer

**Still in master.**

- **Where:** `do_recvfrom()` copies the sender's address into the reply, which shares the RPC buffer with
  the request, before it reads the request's `ee_addr` and `intr_data`.
- **What goes wrong:** by then those fields hold the address's zeroed padding, so the rests packet is sent to
  EE address 0, and for a datagram over 64 bytes the data DMA goes to an address below 64 instead of the
  caller's buffer. `recvfrom()` returns the datagram length, but the buffer holds nothing new. This has been
  so since the 2004 import.
- **Who hits it:** every UDP receive through libps2ips.
- **Our change:** read `ee_addr` and `intr_data` into locals first.
- **Evidence:** review harness: the stock code sends both DMAs to `0x00000000`. A matching hardware
  symptom ("recvfrom returned 14, buffer full of zeros") is recorded in `src/ranet.c`, without who or
  when.

### recvfrom() can return a zeroed or stale sender address

**Still in master.**

`do_recvfrom()` passes `fromlen` to lwIP uninitialised. lwIP 2.2.1 copies only `*fromlen` bytes of the
address when that is under 16, and none when it is 0. Our fix: `int fromlen = sizeof(struct sockaddr);`.
(Source.)

### Sends and receives near 1 KB overwrite the RPC request being handled

**Still in master.**

- **Where:** `static char lwip_buffer[BUFF_SIZE + 32];`, while the data starts at an offset of up to 64
  and is up to 1024 bytes long.
- **What goes wrong:** in ps2sdk's prebuilt `ps2ips.irx` the RPC receive buffer follows `lwip_buffer`, so
  the extra 32 bytes overwrite the request still being handled. A receive then DMAs to an EE address taken
  from the received data, and a send uses a socket, flags and destination taken from the caller's own
  data. `fa7359ff` (2018) introduced it.
- **Who hits it:** any receive or send whose transfer in one call (at most 1024 bytes) is more than
  992 + k bytes, where k is the number of bytes before the buffer's first 64-byte boundary (0 for a
  64-byte-aligned buffer). Examples: more than 992 bytes into or from an aligned buffer, or 1024 bytes
  with k under 32. Large TCP transfers such as HTTP do this.
- **Our change:** `BUFF_SIZE + 64`. That fixes sends as well, though our source comment mentions only
  receives.
- **Evidence:** disassembly of a prebuilt `ps2ips.irx`, and review harnesses for receive and send. Not
  tested on hardware.

### gethostbyname() returns an IOP pointer instead of the address

**Still in master.**

`do_gethostbyname()` copies `&ret->h_addr_list[0]`, the pointer's own bytes, instead of
`ret->h_addr_list[0]`, the address it points to. Every name resolves to an IOP memory address. This has
been so since `e9c45741` (2015). Host test [`test_ps2ips_dns.py`](../.github/scripts/test_ps2ips_dns.py)
fails on master's code and passes on ours.

### Our defect, fixed: a receive with a long unaligned tail lost data

This was a defect in our copy, not in ps2sdk. Because of the 128-byte workaround above, when the unaligned
tail of a receive was longer than 48 bytes, the IRX lowered the returned length after lwIP had already
consumed the bytes, so a TCP stream silently lost up to 15 bytes. It affected the RetroAchievements
flavour's TCP readers in `src/ranet.c` and `src/ratls_ps2.c`. Since 2026-10-27 our copy peeks with
`MSG_PEEK` and then receives only the bytes whose tail fits (`rests_fit()`). lwIP 2.2's TCP peek copies
from the first queued buffer and leaves it queued, so the second receive returns exactly what it asks
for and the rest waits for the next call. A receive therefore returns at most that first buffer, usually
one TCP segment, which `recv()` allows. A UDP datagram with such a tail still arrives up to 15 bytes
short, as if the caller's buffer were smaller, because a datagram cannot be continued. A peek that
returns 0 is followed by a non-blocking 0-byte receive, so an empty UDP datagram is consumed instead of
being returned forever (found by review the same day, before release). Host test
(`test_ps2ips_recv_tail.py`: 8 failures on the old code); lwIP's peek is modelled from its 2.2.1 source,
not run.

### Seen in ps2ips, not changed here

- `do_accept()`, `do_getsockname()` and `do_getpeername()` pass `addrlen` uninitialised. lwIP then copies
  only that many bytes, so a reply can carry uninitialised stack bytes.
- `do_setsockopt()` copies an EE-supplied `optlen` into `optval[128]` with no bound, and the EE side does
  not limit it either.

(Both source.)

## atad (ata_bd)

Our copy is ps2sdk's `iop/dev9/atad` at
[`426de26c`](https://github.com/ps2dev/ps2sdk/commit/426de26cc7fe6d3d0e33d5704fa6815061ee9b27)
(2026-07-20), built as ata_bd. Our changes are marked `/* FORK */` and listed in its
[`ORIGIN.txt`](../modules/hdd/atad/ORIGIN.txt). The menu loads it in every flavour; in-game HDD access uses
OPL's own ATA code. Since our copy, master has also gained DVRP workaround changes and vendor-specific
ATA commands (`79bb3112`, `77abbe2e`, `873208c9`, `c9542e61`); those are not defects in our copy.

### A drive that is not ready at the first probe stays undetected

**Still in master.**

- **Where:** `ps2atad.c`. `sceAtaInit()` sets `ata_devinfo_init = 1` before it probes, and
  `ata_init_devices()` returns 0 even when device 0 answered but IDENTIFY failed. In ata_bd builds,
  `_start` probes when the module loads.
- **What goes wrong:** a failed or early probe is latched. Every later `sceAtaInit()` returns the empty
  result without probing again, until the console reboots.
- **Who hits it:** drives still spinning up, slow adapters, and modules loaded straight after power-on.
  `iop/dev9/hdpro_atad` has the same latch; we left it alone.
- **Our change:** latch only on success; return NODEV when IDENTIFY failed; register each unit with BDM
  once. Two costs remain: a failed probe repeats on every call, each attempt waiting up to about 31 s if
  BSY never clears, and `sceAtaInit()` has no lock.
- **Evidence:** the symptom ("40x: HardDisk Drive not detected") was reported on hardware on 2026-07-21;
  the console and drive are not recorded. No hardware result shows that the fix works. Host test
  [`test_bdm_ata_readiness.py`](../.github/scripts/test_bdm_ata_readiness.py) fails with master's
  `sceAtaInit()` and passes with ours.

### On a drive without LBA48, a request past 2^28 sectors goes to the start of the disk

**Still in master.**

- **What goes wrong:** `ata_device_sector_io64()` never checks the request against the drive's capacity
  or the device index, and the 28-bit encoding keeps only LBA bits 0–27. LBA `0x10000000` reaches the
  drive as LBA 0, so a write lands on the partition table area instead of failing.
- **Who hits it:** only a corrupt partition table or a caller bug produces such a request, but the result
  is silent misdirected I/O rather than an error.
- **Our change:** `ata_request_in_range()` refuses the request before any command is sent.
- **Evidence:** review harness (master sends LBA 0); `test_apa_table_safety.py` checks our helper. Not
  tested on hardware.

### A 4Kn drive is driven as if it had 512-byte sectors

**Still in master.**

atad never reads the drive's logical sector size (IDENTIFY words 106 and 117–118). It reports 512 to BDM
and sizes every DMA at 512 bytes per sector, so on a 4Kn drive every LBA lands at eight times the intended
offset. What a real 4Kn drive then does was not measured. Our copy reads the size and refuses any drive
whose sectors are not 512 bytes; it does not add 4Kn support. `test_apa_table_safety.py` checks the
parser. No 4Kn drive has been tested.

### Fixed in master: an LBA48 transfer of 65536 sectors loops forever

[`f30f05eb`](https://github.com/ps2dev/ps2sdk/commit/f30f05ebadacd074690c74bd5ae555675fe25e34) (LAP87,
PR #913, merged 2026-08-27) fixed it. Our copy carries the same change as a backport.

### Our choice: BDM never writes an APA disk's first 128 MiB

`ata_bd_write()` refuses a write below LBA `0x40000` when LBA 0 carries the APA magic or cannot be read.
A loader that mounts FAT/exFAT and APA on the same disk wants this guard; it is not a ps2sdk defect.

## APA (ps2hdd-osd)

Our copy is ps2sdk's `iop/hdd/apa` and `iop/hdd/libapa` at
[`3e46a44a`](https://github.com/ps2dev/ps2sdk/commit/3e46a44a21db66f42a56320b6f64bfc52ea279f8)
(2026-09-03); master has not changed those paths since. It is built as ps2hdd-osd and loaded by the menu.
[APA safety](APA-SAFETY.md) explains why the fork limits writes. PFS stays ps2sdk's prebuilt.

### apaSetPartErrorSector writes through NULL when the cache is exhausted

**Still in master.**

- **What goes wrong:** `libapa/src/apa.c` does `clink = apaCacheAlloc();` and then uses `clink->header`
  with no NULL check. With the cache exhausted, `apaSaveError()` zeroes 512 bytes at whatever address is
  stored at IOP `0x14` and writes that buffer to LBA 7.
- **Who hits it:** PFS reporting a disk error, or a caller clearing the error record, while the cache is
  full. The default cache holds three buffers, and the next defect leaks them.
- **Our change:** we no longer write error records at all (one of our choices below). ps2sdk needs a NULL
  check; `apaGetFormat()`, `apaJournalRestore()`, `hddFormat()` and `apaOpen()`'s create path have the same
  unchecked pattern.
- **Evidence:** source. `test_apa_table_safety.py` checks only that our copy no longer allocates there.

### A failed error-record read leaks a cache buffer

**Still in master.**

`apaGetPartErrorSector()` returns `-EIO` without `apaCacheFree(clink)` when its read fails. After three
failures, with the default cache, every allocation fails until the module is reloaded. Our copy frees the
buffer. (Source; no test.)

### O_CREAT with no size divides by zero

**Still in master.**

Opening `hdd0:name` with `O_CREAT` and no size field leaves the size at 0. When no free block exists,
`hddAddPartitionHere()` divides by it (`part_end % params->size`). When one exists,
`apaInsertPartition()` halves that block down to zero length, writing each split (source reading, not
run). Our copy refuses every create, so it cannot reach this and has no direct fix. ps2sdk could reject a
size of 0 for `O_CREAT` with `-EINVAL`. (Source.)

### HIOCTRANSFER's bounds check wraps

**Still in master.**

`hdd_fio.c`, `ioctl2Transfer()`, checks `length < sector + size`, which wraps at 2^32. A huge sector
passes, and the transfer, writes included, can land anywhere on the disk. Our check:
`sector > length || size > length - sector`. (Source; `test_apa_table_safety.py` checks the text.)

### A header claiming more than 64 sub-partitions indexes past parts[]

**Still in master.**

`apaOpen()` copies the on-disk `nsub` without checking it against `APA_MAXSUB` (64). `ioctl2Transfer()`
then accepts sub numbers up to that count and reads a start and length from beyond the 65-entry `parts[]`
array, so the I/O can go to an arbitrary LBA. Our copy refuses `nsub > 64` in `apaOpen()`. Still
unbounded in both: `apaRemove()`'s sub loop (our copy cannot reach it) and the caller's index in
`HIOCGETSIZE` and `HIOCGETPARTSTART`. (Source; checked as text.)

### Listing a partition with a huge sub-partition count can hang

**Still in master**, since `15efee2a` (2025-07-09).

`fioGetStatFiller()` sums `subs[i].length` for every `i` below the on-disk 32-bit `nsub`. It reads past
the header, and a large value loops up to about 2^32 times during a directory listing. Nothing is written.
Our copy also stops at `APA_MAXSUB`. (Source; checked as text.)

### A signed 1 << 31

**Still in master.** Latent.

`hdd.c`, `hddAddPartitionHere()`, computes `(u32)(1 << i)` with `i` up to 31, which is undefined behaviour
in C; GCC produces the expected value. Our copy uses `1U << i`. (Source.)

### Our choices in the APA driver

None of these is a ps2sdk defect; a game loader simply does not need these writes.

- A write fence: nothing is written to LBA 0–7 except a whole, valid `__mbr` header at LBA 0. On a 512e
  drive LBA 0–7 share one physical sector with the partition table.
- Error records at LBA 6 and 7 are logged, not written. Worth knowing for ps2sdk: `apaGetFormat()`
  treats unexpected data in LBA 6–7 as "not formatted", so a damaged error record alone makes ps2hdd
  report a good disk as unformatted.
- Walking the partition chain no longer repairs a mismatched `prev` link, which was a write during what
  callers expect to be a read.
- Format, create, remove, rename, sub-partition edits, OSD MBR and raw sector writes return `-EACCES`.

[`test_apa_table_safety.py`](../.github/scripts/test_apa_table_safety.py) covers them on the host. None
has been tested on hardware, including power-cut tests.

### Seen in APA, not changed here

Since `f978fb75` (2025-01-26), `hdd.c` runs `apaJournalRestore()` only when a drive's status is not 1.
At that point the status is 1 for every present, unlocked drive, because the format check comes later. So
ps2hdd built for ATA never replays the APA journal at boot. Our copy has the same line. (Source reading,
not run.)

## BDM

Our copy is ps2sdk's `iop/fs/bdm` and `iop/fs/libbdm` at
[`3e46a44a`](https://github.com/ps2dev/ps2sdk/commit/3e46a44a21db66f42a56320b6f64bfc52ea279f8)
(2026-09-03). The menu loads it in every flavour. In-game, OPL's cdvdman still links ps2sdk's libbdm, but
uses only its unchanged defragmentation code. Since our copy, master has fixed two of these defects
independently.

### Fixed in master: a failed cache refill returns another block's data

`bd_cache.c`, `_read()`, ignored the result of its 8-sector refill and returned the evicted block's bytes
as the requested sectors, then kept them cached. A small read that misses the cache in a device's last 7
sectors always took that path. Master fixed it in
[`e18d7cc1`](https://github.com/ps2dev/ps2sdk/commit/e18d7cc1b4fac672d71ecafcd8c220b73942ad2a) (PR #935,
2026-10-06); ours dates from 2026-09-14. Master caches a partial block and turns a short read into -1;
ours reads straight into the caller's buffer and returns the driver's result.
[`test_bdm_cache.py`](../.github/scripts/test_bdm_cache.py) fails on our pin's `bd_cache.c` and passes on
master's.

### Fixed in master: GPT partitions after an unused entry are invisible

The GPT scan stopped at the first entry with an all-zero type GUID, which only marks that entry unused.
Master fixed it in
[`65f988c4`](https://github.com/ps2dev/ps2sdk/commit/65f988c4730de1a9e833839607e28735fbe25e7a) (PR #933,
2026-10-05); ours dates from 2026-09-15. Master's fix leaves the scan unbounded (next entry).

### Master's GPT scan has no bound

**Still in master**, introduced by `65f988c4`.

- **What goes wrong:** `part_driver_gpt.c` now scans until the index reaches the header's
  `partition_count`. Nothing checks that count: the header CRC is a TODO, and the count is not clamped to
  the space before `first_lba`. A header with a valid signature and a garbage count makes mount read one
  sector per four entries until a read fails, up to about 2^30 reads. The inner loop also parses entries
  past the count. Nothing is written, but mount runs for hours.
- **Our change:** scan every entry only when the entry array fits in the 2048 sectors before `first_lba`;
  otherwise stop at the first unused entry as before. The index is unsigned and the inner loop is bounded.
- **Evidence:** [`test_bdm_partitions.py`](../.github/scripts/test_bdm_partitions.py) (a garbage count
  reads at most three sectors). Master's behaviour is source reading.

### GPT partitions are one sector short

**Still in master.**

`part_driver_gpt.c` sets `sectorCount = last_lba - first_lba`, but `last_lba` is inclusive, as ps2sdk's own
`gpt_types.h` says. Our fix adds 1. It matters once partition I/O is bounded (next entry).
(`test_bdm_partitions.py`.)

### Partition reads and writes are not bounded by the partition

**Still in master.**

`part_driver.c`, `part_read()` and `part_write()`, add the partition offset and pass the I/O on without
checking it against the partition's size. FatFs trusts the boot sector's size, so a filesystem that claims
more sectors than its partition holds writes into the next partition. Our copy refuses I/O past the end,
written to be overflow-safe; it needs the previous fix. (`test_bdm_partitions.py`.)

### A device whose sectors are not 512 bytes overflows the block cache

**Still in master.**

`bd_cache.c` slots hold 8 × 512 bytes and every offset assumes 512, but `bdm_connect_bd()` creates a cache for
every whole device (`parNr` 0), whatever its sector size. A device with 4096-byte sectors writes 32 KiB into
each 4 KiB slot, past the end of the allocation once a high slot is used, and cached reads return wrong data.
Our `bd_cache_create()` returns NULL when the sector size is not 512. (The overflow is source reading;
`test_bdm_partitions.py` checks the refusal.)

### A 4K-sector device is offered to drivers that use 512-byte buffers

**Still in master.**

`bdm_try_mount()` offers every device to every filesystem driver. The MBR probe reads one sector into a
512-byte buffer, the GPT probe reads into 512-byte halves, and ps2sdk builds FatFs with `FF_MAX_SS` 512.
An uncached probe of a 4096-byte device overruns a 512-byte heap buffer. Our copy never offers a device
whose sectors are not 512 bytes; ps2sdk might prefer real 4K support. (Source; the refusal is checked as
text.)

### bd_cache_create writes through NULL when IOP memory runs out

**Still in master.**

Neither `AllocSysMemory()` result in `bd_cache_create()` is checked, and the second asks for about 131 KB.
Our copy frees what it got and returns NULL; BDM then uses the device without a cache.
(`test_bdm_partitions.py`.)

### The connect log line divides by zero

**Still in master.**

`bdm_connect_bd()` prints the size as `sectorCount / ((1000 * 1000) / sectorSize)`, which divides by zero
when the sector size is 0 or above 1,000,000. ps2sdk's usbmass_bd connects a device even when its warm-up
failed, from a slot whose sector size is still 0 if it was never used, so this needs no unusual hardware.
A prebuilt `bdm.irx` traps (`break 7`) on that path. Our copy prints
`sectorCount * sectorSize / (1000 * 1000)`. (Source and disassembly; neither the trap's effect nor the
size-0 device has been seen on hardware.)

### The GPT parser divides by zero for sectors under 128 bytes

**Still in master.** Latent.

`entriesPerSector` becomes 0, and the parser then computes `i % entriesPerSector`. Our copy refuses such a
device. (Source.)

### The MBR probe leaks its buffer when sector 0 cannot be read

**Still in master.**

`part_connect_mbr()` returns without `FreeSysMemory(pMbrBlock)` when the read fails. BDM retries the mount
on every mount event, so the 512-byte leak repeats. Our copy frees it. (Source.)

### Our choice: report refused devices

Our copy marks a refused device and fires the mount callback for it, so OPL can show code 500. That
changes what the callback means, so it is not meant for ps2sdk.

### Seen in BDM, not changed here

- `part_connect_gpt()` returns -1 when a later entry sector cannot be read, after it has already
  connected earlier partitions.
- A failed allocation in the GPT parser returns 0, which reads as success.

(Both source; the effects were not checked.)

## bdmfs_fatfs

We do not vendor this one. CI rebuilds the SDK's own driver with
[`install_safe_bdmfs.py`](../.github/scripts/install_safe_bdmfs.py) before `make`. It replaces
`get_frag_list()` ([`bdmfs-vmc-fragment-walk.c`](../.github/patches/bdmfs-vmc-fragment-walk.c)), fixes
`O_EXCL`, and adds our VMC reservation calls. Every CI release flavour (except two Korium comparison
builds) embeds the rebuilt driver. A local `make` without the installer embeds the stock one, and so
does the Neutrino that RiptOPL bundles. A
ps2sdk-style version of the walker fix, with tests, is on
[NathanNeurotic/ps2sdk PR #1](https://github.com/NathanNeurotic/ps2sdk/pull/1); it has not been offered to
ps2sdk.

### A FAT error or a short chain is reported as one contiguous extent

**Still in master**, since `8b6c3100` (2022).

- **What goes wrong:** `fs_driver.c`, `get_frag_list()`, stops at any next-cluster value of at least
  `n_fatent`. FatFs returns `0xFFFFFFFF` for a disk read error, and bad-cluster markers and out-of-range
  numbers are as large, so each of these ends the walk as if the file ended there. The walk is never
  compared with the file size. `USBMASS_IOCTL_CHECK_CHAIN` then answers "contiguous".
- **Who hits it:** CHECK_CHAIN and GET_FRAGLIST callers when a FAT read fails or the chain is damaged.
  Upstream OPL enables a VMC when CHECK_CHAIN says 1 and lets its memory card emulator write the whole
  card's range from the file's first sector, so it can overwrite sectors the file does not own.
- **Our change:** walk exactly the clusters the file size needs. A read error, an early end, or a last
  link that is not an end marker returns `-EIO`, and CHECK_CHAIN passes errors through.
- **Evidence:** [`test_bdmfs_frag_walk.py`](../.github/scripts/test_bdmfs_frag_walk.py) fails on the stock
  walker and passes on ours. Not tested on hardware.

### The fragment query hangs the IOP on an empty file, a loop or a free entry

**Still in master.**

The walk ends only at a cluster of at least `n_fatent`, and `get_fat()` returns 1 for any cluster below 2.
So it spins forever on a 0-byte file (start cluster 0), on a free or value-1 entry inside a chain, or on a
volume unmounted under an open file; a chain that loops back never ends either. It runs under the
filesystem lock, so every other bdmfs_fatfs call, and disconnecting the device, block too. Our walker
returns 0 for an empty file, stops after the expected number of clusters, and rejects clusters below 2.
(`test_bdmfs_frag_walk.py` covers loops, a free entry, a value-1 entry and a 0-byte file on our walker.
Its 0-byte file has start cluster 2, so it does not reproduce the stock walker's hang on start cluster 0;
only a review harness does.)

### The fragment list after the device is gone reads through NULL

**Still in master.**

After a disconnect or a STOP devctl, an open file's block device is NULL, and `get_frag_list()` reads
`bd->sectorOffset` through it. It also writes through a NULL `rdata` when `rdatalen` is not 0, and
truncates an extent of more than 2^32 sectors. Our walker refuses all three. After a disconnect or STOP,
`f_unmount()` has already cleared `fs_type`, so the walker returns `-EINVAL` (0 for an empty file), and a
`-ENODEV` check on the block device is a backstop. A NULL `rdata` gives `-EINVAL`, and an extent of more
than 2^32 sectors gives `-EOVERFLOW`. (Source. The host test models the lost device as a NULL block
device with `fs_type` intact and checks only for a negative result. The `-EOVERFLOW` path is not
exercised.)

### O_CREAT | O_EXCL opens or truncates an existing file

**Still in master.**

`fs_open()` maps `O_CREAT` to `FA_OPEN_ALWAYS` and never looks at `O_EXCL` (`0x0800`), which libcglue does
pass down. An exclusive create of an existing file succeeds, and truncates it if `O_TRUNC` is also set.
Our patch maps `O_CREAT | O_EXCL` to `FA_CREATE_NEW`. A refused open still returns `-FR_EXIST` (-8), not
`-EEXIST`. (Source; no test runs the patched `fs_open()`.)

### Our addition: reserve a contiguous file

We build FatFs with `FF_USE_EXPAND` 1 and add private calls that reserve and verify a single-extent file
for native VMCs. It is not a ps2sdk patch as it stands. One reason for its odd shape: `fs_ioctl2()`
returns 0 for an unknown command, so 0 cannot tell "unsupported" from "done", and our calls return
positive magic values instead.

### Seen in bdmfs_fatfs, not changed here

- `USBMASS_IOCTL_GET_DRIVERNAME` copies `mounted_bd->name` without a NULL check, and
  `USBMASS_IOCTL_GET_LBA` uses `bd` the same way.
- Handlers return negated FatFs codes instead of `-errno`: a missing file gives -4, which the EE reads as
  `EINTR`. OPL works around it.
- `fatfs_fs_driver_get_mounted_bd_from_index()` tests `index > FATFS_FS_DRIVER_MOUNT_INFO_MAX` where `>=`
  is meant; probably unreachable.

(All source.)

## i.LINK

Our copies of `IEEE1394_bd` and `iLinkman` come from ps2sdk master `329e2bb`, which has not changed them
since, so nothing below is fixed upstream. Every flavour embeds both, and we also replace the copies in
the bundled Neutrino. POPStarter's i.LINK driver comes from an older copy (BDMAssault) with the same
changes, plus ps2sdk's own SBP-2 direction fix (`5eb6bbc6`, `0123ebbc`).

None of these changes is confirmed on hardware. Console reports so far are mixed. Before the changes,
games listed and Ember booted, but native OPL, Neutrino and POPStarter did not. The latest report, after
the first of the changes, has Ember working, native OPL intermittent, and Neutrino and POPStarter failing
([i.LINK audit](ILINK_CODE_AUDIT_2026-10-22.md)). Our host findings do not establish what caused the
failures. Several of the `scsi.c` defects are also in `iop/usb/usbmass_bd/src/scsi.c`, and some
`sbp2_driver.c` ones in `iop/iLink/IEEE1394_disk`.

"Host test" here means a test in this repository that fails on ps2sdk's code: for some entries, an earlier
version of the test, because the current one needs functions only our copy has. "Source" on an entry means
the ps2sdk side was only read; our side is host-tested unless stated.

### IEEE1394_bd

All ten ps2sdk defects below are **still in master**. The entries headed "Our defect" and "Our choice"
are about our copy, not ps2sdk.

#### After an IOP reset the drive may never attach

The driver never logs out, so a new instance after an IOP reset can find the drive still holding the old
exclusive login; SBP-2 keeps it for about 1 s after the bus reset, longer on some bridges.
`initConfigureSBP2Device()` tries LOGIN 5 times, 200 ms apart, then gives up until the next bus reset. A
unit whose management timeout is 0 also times out after one 50 µs poll. Our copy retries for up to 5 s and
waits for management ORBs per the unit's timeout (500 ms when 0, at most 5 s). Host test
(`test_ilink_bd_reset.py`, first version). No bridge's login hold time was measured.

#### TEST UNIT READY has no limit and no delay

`scsi_warmup()` repeats TEST UNIT READY and REQUEST SENSE forever, with no pause. A drive that never
becomes ready holds the bus-reset thread, so no device is published and later bus resets are never
handled. Our copy polls at most 300 times, 100 ms apart, within 30 s. Host test.

#### A drive that failed setup is still offered to BDM

`scsi_connect()` ignores `scsi_warmup()`'s result and connects the device anyway, with whatever sector size
the slot had (0 for a fresh slot), and a READ CAPACITY block length of 0 is accepted. The slot stays taken by
the half-set-up device until the next bus reset disconnects it. Our copy connects only after a successful
warm-up and frees the slot otherwise. Host test (`test_ilink_bd_reset.py`, `test_ilink_scsi_geometry.py`).

#### Fetch-agent setup reads the previous status and frees its ORB too early

After LOGIN, the shared status FIFO still holds LOGIN's status. `ieee1394_InitializeFetchAgent()` waits
without clearing it, returns at once, and frees the dummy ORB while the target may still fetch it. It ignores
the wait's result and reports success whenever the ORB_POINTER write went through. Our copy clears the status,
keeps the ORB until its own completion, and passes failures on. Host test (`test_ilink_sbp2_completion.py`, an
earlier version: 12 failures on ps2sdk's code). `IEEE1394_disk` frees its dummy ORB the same way.

#### A command can complete on the wrong status, or wait forever

All devices share one status FIFO, and `ieee1394_Sync()` accepts any status without matching its ORB, so
unsolicited status or another device's status completes the current command while the target may still
DMA into the caller's buffer. The wait has no timeout and no bus-reset exit, and a failed ORB_POINTER
write is ignored. LOGIN's ORB lives on the stack although that wait can time out. Our copy gives each
device its own FIFO, matches the ORB, stops after 30 s or a bus reset, and keeps ORBs in resident memory.
(Source.)

#### After a DEAD status the next command hangs

When a status sets the dead bit, nothing resets the fetch agent, and under SBP-2 a dead agent fetches no
new ORBs. The retries then publish ORBs that are never fetched. Our copy resets the agent before the next
command. (Source.)

#### Every failure reports sense key 1, and an extended GOOD status fails

`ProcessStatus()` computes `(data[0] >> 16) & 0xF` on a `u8`, which is always 0 and is then forced to 1,
so the real sense key is always lost. It also requires a status length of 1, so a bridge that returns a
longer status block for a successful command fails it, and after 16 retries the read or write returns
`-EIO`. Both date from the 2018 import, and `IEEE1394_disk` has the same code. Our copy decodes the sense
key and accepts a longer GOOD status. Our first attempt read the wrong bytes; see the next entry. (Source;
our side is host-tested.)

#### Our defect, fixed: the status decode read the wrong bytes

Like everything the target writes, the status quadlets are stored in host order. The driver reads the
status header, `ORB_low` and the login response without swapping and byte-swaps only data-phase payload,
and ps2sdk's own wait loop, which listed games on hardware, could not end if the header were in wire
order. Our first decode indexed the third status quadlet as bytes in wire order, so `data[1] & 0xf` was
the low nibble of the ASC and the GOOD check read the ASCQ: a CHECK CONDITION whose ASCQ is 0, such as an
unrecovered read error (ASC 0x11, ASCQ 0x00), passed as success. `sbp2StatusReady()` tested the same byte
for 0xff, so a real ASCQ of 0xff looked like a status that had not arrived. Since 2026-10-27 both our
copies read that quadlet as a number: format `q >> 30`, status `(q >> 24) & 0x3F`, sense key
`(q >> 16) & 0xF`. An all-ones quadlet marks a status not yet written; a target would have to send the
vendor-specific format 3 with every bit set to match it. Host test (`test_ilink_sbp2_completion.py`: 6
failures on each copy's old decode). No hardware dump of a CHECK CONDITION status exists, so the
host-order premise rests on the source.

#### Disk capacity is one sector short

`scsi_warmup()` stores READ CAPACITY's last LBA as the sector count, so the last sector is unreachable. The
READ CAPACITY(16) path has the same off-by-one, and does not check its block length or an all-ones LBA.
usbmass_bd uses the same formula. Host test (`test_ilink_scsi_geometry.py`).

#### Sectors larger than 512 bytes overflow the transfer buffer

The driver always allows 127 sectors per request, whatever block size READ CAPACITY reported. With
2048- or 4096-byte sectors, one request copies up to 520192 bytes into the 65024-byte buffer, and the ORB
length field is cut to 16 bits. Our copy sizes requests from the sector size and refuses oversized
commands before publishing them. Host test (`test_ilink_scsi_geometry.py`, `test_ilink_command_orb.py`).

#### Start-up and setup failures are ignored and leak

`init_ieee1394DiskDriver()` ignores failed allocations, event flags and threads, and the module stays
resident anyway. The fetch-agent setup does not check `ORB_size` before writing a management ORB of that
size. A unit that fails setup keeps its transaction context, which leaks. Our copy unwinds and refuses.
(Source.)

#### Our choice: keep memory the target can still reach

Once waits are bounded, a timed-out command may still be fetched or written by the target. Our copy keeps
every ORB, pointer and status block resident, reads through a staging buffer instead of the caller's
memory, and refuses new commands to that storage until the late status arrives. ps2sdk's unbounded waits
do not need this.

### iLinkman

All eleven are **still in master**.

#### A bus reset can deadlock i.LINK

`iLinkSendData()` takes the transmit semaphore and, when the request's bus generation is stale, returns
`-1021` without releasing it. Every later transmission, including the receive thread's responses, blocks
forever. Any 4-byte request that crosses a bus reset triggers it. Our copy releases the semaphore. Host test
(`test_ilink_manager_recovery.py`, earlier versions).

#### A leftover timeout alarm breaks a later transaction

`iLinkSync()` cancels its 0.25 s alarm only when the wait ends without an error. After an interrupt error,
the alarm later marks an unrelated transaction as failed, or wakes a block transfer early. Our copy always
cancels it. Host test (`test_ilink_manager_recovery.py`, earlier versions).

#### Default builds misread packets after an unhandled packet type

`NoResponseHandler()`'s FIFO read sits inside `#ifdef DEBUG_TTY_FEEDBACK`, so in default builds the drain
loop does nothing, and the leftover quadlets are parsed as the next packet's header. Lock transactions and
other unhandled packet types trigger it. Our copy always drains the FIFO. Host test
(`test_ilink_manager_recovery.py`, earlier versions).

#### Block writes report success on errors, or hang

The interrupt handler's cached register is always 0 by the time a waiter reads it, so
`iLinkPHTSendData()`, used for every request that is not 4 bytes, reports errors as success. Split
timeout, missing ACK and bus reset raise nothing it waits for, so it hangs unless the transfer completes,
and its DMA is not stopped on an error. A response sent by the receive thread also clears the event bits a
client request may be waiting on. Our copy latches the errors, stops the DMA and keeps request events
separate. Host test ([`test_ilink_manager_irq.py`](../.github/scripts/test_ilink_manager_irq.py)). The
controller behaviour it simulates has not been observed.

#### Block reads can return before the data arrives

For a block read, `iLinkPHTSendData()` waits only for the transfer to finish, but the response data is
copied into the caller's buffer later by the receive thread. Neither ps2sdk SBP-2 driver issues block
reads. Our copy waits for the response. Host test (`test_ilink_manager_irq.py`).

#### Late, foreign or error responses write caller memory

`ResponseHandler()` does not check the source node, transaction label, bus generation, response code or
length; every quadlet request uses label 1 and every block request label 0x3F, and the target buffer pointer
is never cleared. A response that arrives after its request timed out writes through a stale pointer, often a
stack variable, and an error response counts as success. Our copy matches each response to its request and
rotates labels. (Source.)

#### Two threads can take each other's replies

The public read and write functions take no lock, and the response buffer and events are global. They do
not check the transaction context index either, and a racing IEEE1394_bd thread can pass -1 after a bus
reset. Our copy adds a lock and refuses bad contexts and sizes. (Source.)

#### Incoming requests are checked only at their start

`WriteRequestHandler()` checks only that the start address is under 2 MB. A rejected write leaves its
payload in the FIFO, to be parsed as headers, and the callback runs anyway. `ReadRequestHandler()` can
return memory past the configuration ROM or past 2 MB. Neither checks the packet length. Our copy checks
the whole span, drains what it rejects, and calls back only on success. (Source.)

#### A refused load leaves its interrupt handler running

`_start` ignores failures to create its kernel objects, and when `RegisterLibraryEntries()` fails it
returns without undoing the interrupt handler, thread and allocations it already set up, so the unloaded
module's code keeps running. A second load without an IOP reset triggers this. Our copy unwinds. (Source.)

#### Importing iLinkGetLocalNodeEUI64 calls iLinkTrAlloc

`iLinkman.h` declares `I_iLinkGetLocalNodeEUI64` as import 12, which is `iLinkTrAlloc`; the export table
has it at 25. Our copy uses 25. No ps2sdk module we searched imports it. (Source.)

#### The configuration ROM has wrong offsets, and deleting a unit corrupts it

`iLinkDeleteCROMUnit()` checks neither the index nor whether the slot is used, so a double delete frees
NULL and decrements the count twice. `BuildConfigurationROM()` publishes the new size before its
allocation can fail, and the vendor-ID and textual-descriptor offsets are miscounted. Our copy fixes all of
these. (Source.)

## Other ps2sdk modules

Defects we found in modules we embed unchanged. We worked around them, or left them.

- **usbmass_bd** (`iop/usb/usbmass_bd/src/scsi.c`): the same unbounded TEST UNIT READY loop, the same
  connect-after-failed-warm-up, and the same one-sector-short capacity as IEEE1394_bd above. Its non-mini
  build (`usbmass_bd.irx`, which OPL embeds only in `DEBUG=1` builds) also divides by the sector size in a log
  line. OPL's own `bdmevent` module does not report a device whose sector size is 0 as unsupported. (Source.)
- **hdpro_atad** (`iop/dev9/hdpro_atad`): the same probe latch as atad. We left it, because no HDPro user
  has reported the symptom. (Source.)
- **libcglue and fileXio**: `getdents()` applies `__transform_errno()` twice, so a failed directory read
  leaves `errno` set to `EPERM`, and `__fileXioDreadHelper()` turns every negative result into `-ENOENT`.
  On their own they only change which errno a failed read reports. Every MMCE directory listing ended
  with an error because mmceman's DREAD returned -1 at the end of each directory; our mmceman patch, which
  is not ps2sdk code, makes it return 0. (Source.)
