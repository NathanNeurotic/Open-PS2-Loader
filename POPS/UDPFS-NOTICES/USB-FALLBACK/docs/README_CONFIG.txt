UDPFS CLIENT CONFIGURATION (memory card or USB drive)
=====================================================

The PS2 UDPFS client reads its network settings from two optional files:
IPCONFIG.DAT (the PS2's own address) and UDPFSCONFIG.DAT (the server address).

Each file is looked up in this order, the first one found is used:

    1. memory card:  mc0:/SYS-CONF/ then mc1:/SYS-CONF/
    2. USB drive:    mass:/SYS-CONF/

In the Ember build (make EMBER=1) the memory card is readable only if the
launcher has loaded the memory card modules (e.g. rom0:XSIO2MAN and
rom0:XMCMAN) BEFORE this module: the files are read once, when the module
starts. Otherwise mc0: answers "no device", the default IP 192.168.1.10 is
used unless the files are on the USB drive (folder SYS-CONF). On the USB drive
(FAT/exFAT) the folder name is not case sensitive; on the UDPFS server (Linux)
it is.

The two files are independent: for example IPCONFIG.DAT can be on the memory
card and UDPFSCONFIG.DAT on the USB drive. Without a file, the defaults below
apply.


IPCONFIG.DAT - PS2 IP address
-----------------------------
A single line of text:  IP_ADDRESS NETMASK [GATEWAY]

e.g.:

    192.168.1.10 255.255.255.0 192.168.1.1

Files (in this order):

    mc0:/SYS-CONF/IPCONFIG.DAT
    mc1:/SYS-CONF/IPCONFIG.DAT
    mass:/SYS-CONF/IPCONFIG.DAT

- An unreadable or invalid file is treated as if it were missing. Invalid means:
  IP 0.0.0.0, 127.x or multicast; an invalid netmask; or an IP equal to the
  network address or the broadcast address.
- Empty lines and comments (# or ;) at the start of the file are allowed, as
  are CRLF line endings and a BOM. Extra fields after the gateway are ignored.
- The gateway is not used: the ministack does not route, so the server must be
  on the same network as the PS2.
- Without a valid file, the default IP 192.168.1.10 with netmask 255.255.255.0
  is used (the same as UDPBD and Neutrino), which keeps compatibility.


UDPFSCONFIG.DAT - UDPFS server IP address
-----------------------------------------
A single line of text:  IP_ADDRESS

e.g.:

    192.168.1.11

Files (in this order):

    mc0:/SYS-CONF/UDPFSCONFIG.DAT
    mc1:/SYS-CONF/UDPFSCONFIG.DAT
    mass:/SYS-CONF/UDPFSCONFIG.DAT

- If present (and in the same subnet as the PS2), it takes precedence: the
  DISCOVERY goes directly to that IP and an INFORM is accepted only from it.
- If it is missing, the server is looked up with a broadcast DISCOVERY (6
  packets over a 3 s window at boot) and the first one that answers is used.
- If the address in the file is outside the PS2's subnet, it is ignored and
  broadcast is used instead.


Transport behavior
------------------
After the discovery, packets go to the server as Ethernet unicast (the MAC
address is taken from the INFORM). If the server does not answer two requests
in a row, the data port is forgotten and the next request performs the
discovery again.


Ember build (make EMBER=1)
--------------------------
Two builds exist, one per program:

    make               POPStarter build (bdm_udp_fs_assault.irx): UDPFS is
                       used only for POPS/ and POPS0/ ... POPS9/ *.VCD files.
    make EMBER=1       Ember build (bdm_udp_fs_assault_ember.irx; with DEBUG=1
                       bdm_udp_fs_assault_ember_debug.irx): UDPFS is used only
                       for EMBER/games/<folder>/<name>.cue and <name>.bin
                       (one folder level; any .cue/.bin in the folder, so CDs
                       with several .bin files work; maximum path length 255
                       characters).

In both builds the USB drive is tried first, only read-only opens and getstat
go to the network, and the configuration files are the same.

Differences of the Ember build:
- Ember loads the module once and never resets the IOP, so the configuration
  is read from the memory card once at start and nothing is copied into IOP RAM
  (see the next section: it applies to the POPStarter build only).
- The /EMBER/ folder itself (settings.txt, bios.bin, the virtual memory cards,
  which Ember writes) must stay on the USB drive: UDPFS is read-only and only
  adds the .cue/.bin files that are missing from the drive.
- Ember calls getstat on the .bin before opening it. The Go server (udpfsd)
  answers -5 (EIO) to GETSTAT of a file that is not open; the client then asks
  with OPEN + CLOSE and takes the size from the reply.
- Ember reads the .bin in blocks of 16384 bytes from positions that are
  multiples of 2352 (not of 512). The unaligned head and tail of each read
  go through a one-sector cache per open file, so a sector shared by two
  consecutive reads is requested once.
- File and folder names on the server are case sensitive on Linux: the folder
  must be EMBER/games/<folder>/ exactly as Ember asks for it.


How the memory card files reach the module (POPStarter build)
-------------------------------------------------------------
POPStarter loads this module twice: once before and once after an IOP reset.
In the first load the memory card is readable; after the reset the memory card
driver ("mc0:") is gone (opening it returns -19, ENODEV). Loading the system
modules that provide it again (rom0:XSIO2MAN and rom0:XMCMAN) from this module
made the game controller stop working, because it interferes with the modules
POPStarter loads itself. So the module never loads any system module.

Instead, the IOP reset does not clear the IOP RAM, and the files are carried
across it:

- First load (the memory card answers): the two files are read and copied, with
  a signature and a checksum, into three windows of IOP RAM (0x1D0000, 0x1E0000
  and 0x1F0000, 256 bytes each) taken with AllocSysMemory at a fixed address, so
  nothing in use is overwritten. The copies are written also when the files do
  not exist, so an old copy is never reused.
- Second load (mc0: gives ENODEV): the first copy that passes the signature and
  checksum check is used and every valid copy is wiped. A damaged copy (another
  module wrote over it) is neither used nor touched.
- Three copies because the reset may overwrite one of them (in a test on
  hardware, 19 of 20 windows survived; the lost one was at 0x100000).
- Each file may be at most 120 bytes; a larger or empty file is ignored.

If the memory card has no file (or no valid copy is left), the USB drive is
read, as described at the top. The USB drive is always there (POPStarter needs
it for the POPS files) and is mounted by this very module. The network thread
starts first (hardware init and Ethernet link negotiation), waits for the drive
to be mounted (at most 10 s, also when the card provided the files), reads the
files that the card did not provide and then starts the discovery. Without a
drive and without files, the defaults apply: default IP and broadcast
discovery.

- The Ethernet link comes up seconds after smap_init() returns. The client
  waits for it (up to 4 s) before the first DISCOVERY; without a link (cable
  unplugged) no discovery window is spent. fs_open waits up to 14 s for the
  client to be ready.


Diagnostics
-----------
Build with "make DEBUG=1" to enable the IRX log (with the BDM/FatFs traces), or
with "make TTY=1" for a release build that only sends the "UDPFS: ..." lines of
the client. The log is sent over UDP tty on port 18194:

    nc -u -l 18194

A normal build (neither option) sends nothing: it is built with -DNO_TTY.

Configuration messages (printed together with the INFORM line):

    UDPFS: cfg src: mc ip N srv M, stash K          first load: bytes read from the
                                                    memory card, copies written
    UDPFS: cfg src: stash K copies ip N srv M       second load: valid copies found
                                                    and bytes of each file
    UDPFS: PS2 IP a.b.c.d (IPCONFIG.DAT | default)
    UDPFS: server: a.b.c.d (UDPFSCONFIG.DAT)
    UDPFS: server: broadcast
    UDPFS: server: outside subnet, broadcast

Discovery messages:

    UDPFS: INFORM from <ip> port <p>, server <ip>, MAC <mac> (unicast | Ethernet broadcast)
    UDPFS: no INFORM accepted after N DISCOVERY packets (INFORMs seen: M)
    UDPFS: no reply to unicast, falling back to Ethernet broadcast
    UDPFS: server restarted (data port X -> Y), new session

Request messages:

    UDPFS: open -> H size S                         a file was opened on the server
                                                    (H < 0: the server does not have it)
    UDPFS: req seq N failed: rx .. dseq .. dport ..  a request got no reply after all
                                                    its attempts (counters of the
                                                    receive handler, for diagnosis)

Start-up timing (DEBUG=1): once the client is ready, lines of the form

    UDPFS: t(ms) usb 1145 ip 1145 cfg 1209 dev9 1144
    UDPFS: t(ms) smap 1145 link 3021 disc 3032 ready 3032

show the milliseconds since the start of the module instance at each phase
(usb = USB drive mounted, cfg = config read, dev9/smap = hardware init,
ip = PS2 IP set, link = Ethernet link up, disc = discovery done). dev9/smap
init and the Ethernet link negotiation (about 3 s) run in parallel with the
USB mount; the discovery starts after the USB drive is mounted and the config
files have been read.

Boot information (DEBUG=1): printed with the timings, one block per instance
of the module:

    UDPFS: args argc=N / UDPFS: argK [text]   arguments given to the module

POPStarter passes only argv[0] ("LBbyEE"), so no setting reaches the module as
an argument.

All reads use BREAD (also verified against udpfs.py). Unaligned reads (the VCD
header at open time) read the head and tail through a one-sector cache per open
file; the client no longer sends READ or LSEEK.

After changing a build knob (DEBUG, TTY, EMBER) run "make clean".


Changelog
---------
- Removed the UDPFS_STATS diagnostic build option (live statistics sent as fake
  GETSTAT requests); DEBUG and TTY remain.
- First request of a session: if the server does not answer seq 0 (it may take it
  for a duplicate of a previous session that sent a single packet), the second
  attempt is sent as seq 1.
- Configuration: IPCONFIG.DAT (PS2 IP) and UDPFSCONFIG.DAT (fixed server IP)
  from mc0:/SYS-CONF/ (then mc1:), otherwise from mass:/SYS-CONF/ on the USB
  drive (same paths for the POPStarter and the Ember build); default IP 192.168.1.10.
- The memory card files are read in the first load of the module and carried
  across the IOP reset in IOP RAM (three checked copies). No system module is
  loaded (restoring the card after the reset broke the game controller).
- Discovery: real-time clock for the INFORM wait (3 s window, 6 packets),
  wait for the Ethernet link, late INFORM accepted while no session exists.
- Server restart during a game: probe DISCOVERY after 2 unanswered attempts,
  session restart, reopen by path if the handle is no longer valid.
- Reads: BREAD only, with a one-sector cache for unaligned head/tail.
- Ember support: make EMBER=1 build, UDPFS used for EMBER/games/<folder>/
  *.cue and *.bin (the POPStarter build keeps POPS/ *.VCD only); GETSTAT
  answered -5 by the Go server is retried with OPEN + CLOSE; paths up to 255
  characters.
- net_ministack.c: arp_add_entry() free-slot check fixed (no behavior change,
  the function is unused).
- Start-up time: the network thread starts first (hardware init and link
  negotiation overlap with the USB mount).
  net_smap.c: the stock driver slept a fixed 3 s waiting for auto negotiation;
  it now polls every 50 ms and continues as soon as it completes (limit
  unchanged).
- Boot discovery sends DISCOVERY at short intervals first (6 packets over the
  3 s window, spaced 150, 150, 300, 600, 900, 900 ms): the first packet is
  often lost right after the link comes up, and waiting 1.7 s for the next
  one cost more than the time saved elsewhere.