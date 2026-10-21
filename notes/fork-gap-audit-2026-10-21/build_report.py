"""Build the dated audit, inclusive ID dispositions, and one deduplicated gap list.

Input snapshots are immutable evidence; this is a documentation generator, not a
claim of automated semantic or physical-console validation.
"""
from pathlib import Path
from bs4 import BeautifulSoup
import json, re, html, collections

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'baseline.html'
LIVE = json.loads((ROOT / 'live-supplement.json').read_text(encoding='utf8'))
OLD = json.loads((ROOT / 'baseline-register.json').read_text(encoding='utf8'))
SOUP = BeautifulSoup(BASE.read_text(encoding='utf8'), 'html.parser')
RIP = '2808a4cd579e4294c520e35149bbfc87d79cce45'
SITE = '4c349e2d5cb42dc2b96777c7cb93c1b73bb84c6e'
GH = 'https://github.com/'
evidence = collections.defaultdict(list)
for tr in SOUP.select('tr'):
    td = tr.find('td')
    if td and re.fullmatch(r'[A-Z]+\d+', td.get_text(' ', strip=True)):
        key = td.get_text(' ', strip=True)
        for a in tr.select('a[href]'):
            if a['href'].startswith('http') and a['href'] not in evidence[key]:
                evidence[key].append(a['href'])
for key in ['DT1','DT2']:
    evidence[key] = ['https://github.com/MiguelQueiroz010/OPL-DS4RTBT/tree/2cf308511b187f8a0b209140f71936dca0bb0bae/modules/ds34bt']
for key,patch in [('RI3','0108-ripps2-ripshot.patch'),('RI5','0104-ripps2-languages.patch'),('RI6','0105-ripps2-ripdisc.patch'),('RI7','0108-ripps2-ripshot.patch'),('RI8','0107-ripps2-search.patch')]:
    evidence[key] = ['https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/'+patch]
for key,path in [('CO4','ee_core/src/ra_overlay.c'),('H4','src/ranet.c'),('N2','src/config.c')]:
    evidence[key].insert(0,'https://github.com/NathanNeurotic/Open-PS2-Loader/blob/2808a4cd579e4294c520e35149bbfc87d79cce45/'+path)

NEW = [
 ('TV1','Recursive ISO discovery outside CD/DVD','FastLoader','Claimed release','https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease'),
 ('TV2','Rename ISO and its associated art, VMC and metadata together','FastLoader','Claimed release','https://github.com/Kyllemn/PS2TVCRT/blob/42c33b5be94cfa990f4a6f1281d0596922d20a46/README.md'),
 ('TV3','Integrated CPS1/CPS2/MVS/PCE/Neo Geo CD ROM library','Retro Arcade','Claimed release','https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease'),
 ('TV4','Emulator return to same game and per-launch 240p/480i/480p','Retro Arcade','Claimed release','https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease'),
 ('TV5','Integrated Windows suite layout/art/VMC preparation','Retro Volt Suite','Companion','https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease'),
 ('TV6','Fixed CRT interface and embedded frontend resources','FastLoader','Design overlap','https://github.com/Kyllemn/PS2TVCRT/blob/42c33b5be94cfa990f4a6f1281d0596922d20a46/README.md'),
 ('TV7','Ember starting-disc selection from grouped PS1 games','FastLoader','Claimed release','https://github.com/Kyllemn/PS2TVCRT/blob/42c33b5be94cfa990f4a6f1281d0596922d20a46/README.md'),
 ('TV8','Nonrepeating startup background rotation','FastLoader','Claimed release','https://github.com/Kyllemn/PS2TVCRT/blob/42c33b5be94cfa990f4a6f1281d0596922d20a46/README.md'),
 ('TV9','Integrated bulk file/save manager with progress and cancellation','FastLoader','Claimed release','https://github.com/Kyllemn/PS2TVCRT/blob/42c33b5be94cfa990f4a6f1281d0596922d20a46/README.md'),
 ('TV10','Network ISO and artwork serving through Neutrino','FastLoader','Overlap','https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease'),
 ('RI9','Arabic/Persian shaping, bidi and Lao mark layout','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0104-ripps2-languages.patch'),
 ('RI10','Persistent per-source library snapshot with idle revalidation','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0110-ripps2-quicklists.patch'),
 ('RI11','Typed settings destination picker with directory provisioning','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0110-ripps2-quicklists.patch'),
 ('RI12','Power off from paused in-game actions panel','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0106-ripps2-poweroff-star.patch'),
 ('RI13','Per-row star/highlight/platform decorator theme controls','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0106-ripps2-poweroff-star.patch'),
 ('RI14','Managed screenshot rolls, indexed PNG development and SCRn','RIPPS2','Released source','https://github.com/akilluminati47/RIPPS2/blob/e6b3fc9a5ad0bce0c08e30df84b697519aa9c803/elf/patches/0108-ripps2-ripshot.patch'),
 ('H11','Selectable suffix RA mark and smaller unframed cover mark','xeRAbora OPL','Released source','https://github.com/hacan359/Open-PS2-Loader/commit/759b12a2dff0cf49736b27991c73399a7e7971e8'),
 ('H12','Linux ARM64 Raspberry Pi client package','xeRAbora','Companion','https://github.com/hacan359/xerabora/releases/tag/v0.1.0-alpha.19'),
 ('H13','Correct in-game SMAP TX descriptor buffer base','xeRAbora OPL','Fix candidate','https://github.com/hacan359/Open-PS2-Loader/commit/205223e2d5f838674676d6f8c171dd909eb6c01d'),
 ('DT4','Mixed real/emulated multitap slot and two-port poll routing','OPL-DS4RTBT','Released source','https://github.com/MiguelQueiroz010/OPL-DS4RTBT/compare/e016d934e117a645e476564eddfd7f14f0188e01...rt-2.7.0'),
 ('DT5','Controller screen with battery/type and per-pad disconnect','OPL-DS4RTBT','Released source','https://github.com/MiguelQueiroz010/OPL-DS4RTBT/commit/f638621cdd40d834877745bda75fa01dae0e1d84'),
 ('DT6','KH2 SMB+PADEMU memory-footprint correction','OPL-DS4RTBT','Fix candidate','https://github.com/MiguelQueiroz010/OPL-DS4RTBT/releases/tag/rt-2.7.0'),
 ('PX31','Signed INTPL GTE interpolation correction','PSXCore','Experimental source','https://github.com/dnunezx/PSXCore/commit/9d9c7a36c493abd741793fec4dafb018883b0212'),
 ('PX32','GP1 DMA control applied with native worker parked','PSXCore','Experimental source','https://github.com/dnunezx/PSXCore/commit/2f35645aa9c35a4af83feee91da79f39155ced1c'),
 ('PX33','Buffered interlace descriptor publication','PSXCore','Experimental source','https://github.com/dnunezx/PSXCore/commit/dcf1fc868de33a957ae14072145a2d6810abc3ff'),
 ('PX34','Precomputed memory addressing and smaller DMA/GP0/GP1 saves','PSXCore','Experimental source','https://github.com/dnunezx/PSXCore/compare/66c70e9f920c39ebbe8c3d1deb7cfc7a78cf4fc9...0d4348ea5fff50a16c303c5c1910038e65bf7915'),
 ('PX35','Larger adapter capacity and startup planner diagnostics','PSXCore','Experimental source','https://github.com/dnunezx/PSXCore/commit/f1333504bdd43815f295081f434276dcfae80eff'),
 ('LU36','SPU2 ADPCM hardware-loop ambient music','LUNA frontend','Unbundled source','https://github.com/dnunezx/nhddl-luna/commit/1580671bab32d124cc6affaac3a3251d515b4664'),
]
allrows = {r['id']:dict(r) for r in OLD}
for key,title,project,state,url in NEW:
    allrows[key] = dict(id=key,feature=title,project=project,category='October 21 delta',kind=state,state=state)
    evidence[key] = [url]

# Each line is one distinct missing capability. Multiple historical IDs intentionally
# map to a single row. Experimental runtime mechanisms are explicitly labelled.
SPEC = '''
RI5,RI9|Localization|Released source|Version-tolerant keyed language packs, layered fonts and RTL shaping|RIPPS2 uses English-text hashes with fallback and adds Arabic/Persian joining/bidi plus Lao marks/wrapping. RiptOPL remains positional; printf-format validation already exists and is not counted as missing.
OH1,OH12|Theme engine|Source|Declarative HTML/CSS flexbox compilation and reusable C99 console UI runtime|OPHTML compiles layouts to a bounded zero-allocation GS command list and publishes a reusable launcher-core archive; RiptOPL uses its existing theme configuration engine.
OH2|Theme engine|Source|Pre-resolved pairwise HarfBuzz kerning|Font shaping/kerning data is prepared off-console for EE use; separate from having UTF-8 fonts.
OH3|Theme engine|Source|Palette-index theme switching without texture re-upload|Specific instant color-scheme mechanism rather than ordinary theme switching.
OH4|Theme engine|Source|Runtime 2D layout-coordinate offsets for animated expansion|OPHTML runtime layout primitive, beyond RiptOPL's element-specific carousel/list animations.
OH5|Theme engine|Source|Focus-subtree visibility masking with automatic navigation bypass|A coordinated layout/focus-tree mechanism, not simply hiding one image.
OH10,OH11|Theme engine|Source|Bounded binary UI loading and compiler budgets for declarative themes|Fuzzed .uib parsing, alignment checks and hard input/layout safety limits for OPHTML's format. Different architecture; not proof of an exploitable RiptOPL theme bug.
P5|Theme / UI|Partial|Animated game-launch presentation beyond black fade|RiptOPL has launch/video black fades; PS2-Launcher and Titan have their own staged launch animations. Retained as optional presentation, not missing handoff correctness.
K1|Diagnostics|Historical source|Write debug logs to a BDM storage device|Historical uOPL logging output, distinct from RiptOPL's network/debug logging.
LU8|Core|Source|Neutrino in-game return/IGR|RiptOPL has OPL-core IGR; the bundled Neutrino does not implement LUNA's held-combo return path.
LU7|Core|Source|Coordinated Neutrino power-button shutdown|Optical-work drain and DEV9 shutdown on the physical power event; separate from the OPL-core power path.
LU11,LU35|Storage|Partial|Neutrino VMC backing and management for APA/PFS games|RiptOPL supports native-core VMC on APA, but deliberately drops Neutrino APA VMC arguments. LUNA's mapped backing has geometry and fragment limits; save/reload testing remains necessary.
LU12,LU34,TV7|PS1|Source / claim|Grouped PS1 disc sets, starting-disc picker and in-game swaps|LUNA implements ordered two-to-four-VCD sets and swaps in its matching runtime; FastLoader claims an Ember starting-disc picker. RiptOPL's ordinary PS1 listing is already present.
LU13,LU33|PS1 saves|Source|Named PS1 card pairs with import/export, paired backups and recovery|The missing capability is the integrated pair-management lifecycle, beyond existing POPStarter/Ember saves and basic card creation.
RI1,PX21|Save tools|Source|Browse save images and import/export PSU or copy card pairs|Integrated VMC-as-folder/PSU tools and confirmed absent-destination PS1 pair copies; RiptOPL can create/assign cards but does not expose these save-browser operations.
RI2,B5|Save tools|Source / claim|Physical memory-card backup, restore, format and repair UI|Other shells integrate these tools. Optional extension with destructive operations, rather than a missing ability to save a game.
RI3,T3,RI12,LU15|In-game UI|Experimental|Paused in-game actions menu with resume, return and power off|RIPPS2 now enables its panel by default and adds power off; Titan has profile-gated suspend/resume, and LUNA integrates a native PS1 Quit/Play return panel. RiptOPL's reset and RA notices do not provide these menus.
RI6|Disc tools|Released source|Rip optical discs directly to the library or media storage|RIPDISC now exists in builds 105-110: PS2 ISO/split output, PS1 BIN/CUE, audio CD and DVD-video paths. Previous planned status is obsolete; emulator reports are not PS2 acceptance.
RI7,RI14,O13|Screenshots|Released source|Managed in-game screenshot capture and artwork development|RIPSHOT has six-slot rolls, preview/Keep/Delete, ART/MEDIA output, PNG development and SCRn slideshow. RiptOPL inherits optional IGS code, so the gap is this complete managed workflow, not the existence of screenshot code.
B1,LU14,LU20,LU21,TV9|Console tools|Source / claim|Integrated multi-device file explorer and bulk operations|Copy/move tray, rename/delete/mkdir, conflict choices, verified moves, text preview and ELF launch. Launchstation can supply file management externally; it is not embedded in RiptOPL.
RI8|Console tools|Released source|Cross-device file/folder search that opens the matching location|RIPPS2 build 107 implements bounded breadth-first search, cancellation and result navigation; it is no longer merely planned.
TV2|Library|Claimed release|Coordinated game-file rename with art, VMC and metadata migration|FastLoader claims renaming the ISO carries its associated assets, card and settings; display-title editing in RiptOPL is already available.
TV1|Library|Claimed release|Automatic ISO discovery throughout arbitrary folder trees|FastLoader claims four-level discovery outside CD/DVD. RiptOPL's prefix/subfolder navigation is not a whole-drive arbitrary-directory scan.
RI10|Library|Released source|Persistent per-source game-list snapshots with idle revalidation|RIPPS2 caches MMCE/BDM/SMB lists on their source. RiptOPL already has ISO-ID and APA list caches; the missing scope is its equivalent across those other backends.
RI11|Settings|Partial|One settings-destination picker that provisions typed device paths|RIPPS2 offers MC/HDD/USB/MX4SIO/iLink/MMCE and creates its folder. RiptOPL already supports custom/typed paths; this is the guided workflow, not new settings-storage support.
O3|Library|Source|Recently played history containing multiple games|OPLattice retains the last eight, rather than only RiptOPL's remembered last title.
O4|Library|Source|User-selectable alphabetical, reverse, recent and scan-order sorting|Distinct from remembering a selected game and from PS1/PS2 filters.
O9|Library|Source|Per-game launch counts and accumulated play time|A play-history/statistics layer, beyond a last-played selection.
P3|Library|Source|One automatically aggregated library across every game device|RiptOPL's Favorites can span sources and its platform filters mix PS1/PS2; neither aggregates all non-favorite games from every source into one library.
LU5|Library|Design option|Favorites stored per game drive and carried with that drive|RiptOPL deliberately uses a shared cross-device favorites file. This is an alternative persistence policy, not missing Favorites.
LU6|Reliability|Partial|Staged replacement and recovery for last-title and title-ID cache files|Favorites staging/recovery already exists in RiptOPL. Only LUNA's additional last-title/cache coverage remains to compare and extend.
M1|Network UI|Claimed release|Choose among multiple discovered UDPFS servers|Modulo exposes server selection; RiptOPL automatically chooses a server. Existing network-game transport is not missing.
N1|CLI|Source|Generic backend/path forward-boot command line including no-init|NHDDL accepts mode/DVD-path forwarding and reuse of the resident environment; RiptOPL's positional HDD/BDM autolaunch is narrower.
L1|Storage|Source|Extended APA addressing for HDDs above 2 TiB|Different from existing exFAT/GPT large-drive support. Source integration and safe media layout need independent evaluation.
X1|Storage|Historical source|EXT2 filesystem support on USB|E2OPL's legacy filesystem path is distinct from RiptOPL's FAT32/exFAT support; no current hardware regression claim.
DL1|Disc launching|Source|Selectable DKWDRV/PS1VModeNeg physical-PS1-disc handoff|RiptOPL has ordinary disc actions and PS1 image cores; this is the explicit enhanced-disc-launcher handoff workflow.
DL2|Disc launching|Source|Conditional import-disc OSD language override|The enhanced launcher applies an override conditionally for import-disc behavior.
P2|Library|Source|Download cover artwork directly on the PS2|PC artwork tools already work with RiptOPL; the missing operation is the console-initiated download.
U6|Network|Source|Broadcast a game-launch event for a Discord presence listener|A console launch-announcement interface, distinct from an external companion calculating presence by other means.
DB1|Controllers|Source|DualSense over Bluetooth in menu and in-game PADEMU|RiptOPL already has an optional USB DualSense variant; Bluetooth support is the gap.
DB2|Controllers|Source|Wireless device discovery, secure pairing and persisted link keys in the GUI|Distinct from existing DS3 cable pairing and stock DS3/DS4 Bluetooth input.
DT1|Controllers|Source|Automatic RTL8761B/BU Bluetooth firmware loading|Menu and in-game dongle initialization in the Realtek fork.
DT2|Controllers|Source|Extended DS4-clone HID, CRC, handshake and rumble handling|Additional clone protocol/feedback support; existing fake-DS3 workaround is not equivalent.
DT3,DT5,P7|Controllers|Source|Multi-pad connection/type/battery HUD and setup/test/disconnect UI|Combines overlapping pad-status rows rather than counting each fork's screen twice.
DT4|Controllers|Released source|Mixed physical/wireless multitap routing per slot and two-port poll|The rt-2.7.0 source splits real-pad transfers and preserves per-slot choices. RiptOPL has multitap emulation already; this is the additional routing behavior/fix.
P1|Controllers|Source|Xbox One and Series controllers over USB|Requires a controller driver/protocol beyond RiptOPL's DS3/DS4 and optional DS5 paths.
MP1|Controllers|Historical source|Xbox 360 controllers over USB|Separate controller class from Xbox One/Series; implemented in historical modular PADEMU.
MP2|Controllers|Historical source|Generic descriptor-driven USB HID gamepads|Generic report parsing, rather than only a whitelist of controller-specific drivers.
P6|Controllers|Source|Additional Steam Controller, Shanwan PS3 and GP300 USB support|Specific protocol/device coverage in PS2-Launcher, not a claim that every clone is supported there.
RR1|Controllers|Source|USB Driving Force wheel presented as a negCon|An experimental wheel translation path, distinct from ordinary pad emulation.
T9,B6|Controllers|Experimental|Xbox Bluetooth/BLE and USB keyboard/mouse input classes|Titan's modern-input contracts are source/host validated with target acceptance pending; BoliviaOS separately advertises USB keyboard input.
P4|In-game UI|Source|Hold SELECT alone to leave a game|Alternative configurable exit interaction, beyond existing multi-button IGR.
O1|Theme / UI|Source|Two-axis flat tile-grid library navigation|RiptOPL's linear Coverflow and PSBBN perspective fan do not provide the same grid.
LU2|Theme / UI|Source|Depth-sorted orbital ring library view|A complete selectable ring renderer with perspective and depth falloff.
LU9,LU26|Theme / UI|Source|Projected 3D case grid with case styles and inspection|LUNA's projected case layout and PS1 case presentation; distinct from flat tiles and PSBBN Flow.
LU10,LU27,LU29|Theme / UI|Experimental|Ambient-orb Scroll view with logo/title fallback and controls|A full browsing view, not a claim that RiptOPL lacks animation or missing-art text.
LU4,LU25|Theme / UI|Source|Continuously rotating disc-label art and paired-art presentation|RiptOPL already supports ICO/LGO/COV artwork; animation is the differentiated capability.
LU23,LU24,LU28|Theme / UI|Design option|LUNA-specific view toggles, Random Scan and presentation presets|Includes view enablement, orbital auto-browsing, glass/font/background options; generic theme selection already exists in RiptOPL.
O10|Theme / UI|Source|SHELF dashboard/sidebar with Home, Library, Apps and Settings|An optional complete shell presentation rather than a new game source.
CO1|Theme / UI|Source|Interpolated XMB category and game-list rails|Caduceus OPL's specific navigation model.
CO2|RetroAchievements UI|Partial|Game-details card with automatic RA support/status checks|RiptOPL already has achievement support checks and a browser; the additional automatic details-card workflow remains different.
CO7|Device UI|Source|Initialize manual devices asynchronously when their category receives focus|RiptOPL has manual and automatic discovery, but not this specific category-focus policy.
OF1|Theme / UI|Experimental|Dedicated carousel/device dock and system-status HUD primitives|OPL FUTURE's optional interface architecture; no generalized console-performance claim.
E1|Theme / UI|Experimental|Unified controller, memory-card, storage and network dashboard|OPL Evolution's integrated status surface; ordinary individual status indicators overlap existing behavior.
DN1|Theme engine|Source|Configurable framebuffer blur/frosted-glass compositing|A new render/compositing primitive rather than an image that resembles blur.
DN2|Theme engine|Source|CardShelf element and crossfading cover-art wallpaper|Daniel's PS5-style theme primitives; generic carousel/artwork display already exists.
W1|Theme engine|Source|Load an entire theme from a TAR archive|RiptOPL already loads ART/CFG/CHT archives; the missing archive type is THM/theme resources.
W2,O7|Theme engine|Source|Theme X-position controls specifically for widescreen layouts|wsX and x_scaled address the same broad layout requirement and are counted together.
W3|Theme engine|Source|Live PADEMU/GSM/cheat-state icons supplied to themes|Distinct from static metadata badges in AttributeImage.
W6|Theme / UI|Design option|Info-only page without list navigation|An alternative information-screen interaction policy.
O2|Theme engine|Source|Bind image elements to non-selected neighboring game rows|Offset-driven hero/filmstrip layouts.
O5|Theme engine|Source|MenuTabs strip showing all devices and custom labels|Existing MenuText/current-device selection is narrower.
O6|Theme engine|Source|Theme-controlled game-count prefix and suffix|Current RiptOPL GameCountText uses the localized FILE_COUNT format.
O11|Apps|Source|Per-app subtitle metadata and display|A separate subtitle field in the app's title.cfg.
RI13|Theme engine|Released source|Per-row star, highlight and platform-decorator controls|RiptOPL has Favorites and decorators; the configurable star column/highlight/PS1/PS2/app controls are additional.
TV8|Theme / UI|Claimed release|Cycle startup backgrounds without repeats until the set is exhausted|Specific shuffle-bag behavior advertised by FastLoader, not basic background/theme support.
H11|RetroAchievements UI|Released source|Selectable suffix RA mark and a smaller unframed cover mark|RiptOPL still builds an RA prefix and has no gRABadgeSuffix choice. Alphabetic sorting must be checked separately before attributing a sorting bug.
T1|Enhancements|Source|Independent graphics-enhancement files and selection|Titan separates ENH enhancements from gameplay CHT cheats, with separate per-game choices and metadata.
T4|Profiles|Source|Named system users whose selected profile chooses an exclusive VMC|Different from per-game card assignment alone.
T5|System UI|Source|Notification center with retained activity/download progress|RiptOPL has transient notifications rather than a retained activity service.
T2|System platform|Source|Installable native app packages and an in-process application SDK|Titan TPKG/runtime services; ordinary external ELF launching is already present.
T6|System tools|Source|Integrated lightweight interactive web browser|HTTP text/link browsing and bridge-backed HTTPS, rather than HTTP game streaming.
T7|System tools|Source|In-console staged/rollback-capable system updater|RiptOPL distributes release kits instead of performing transactional console installation.
T10|System platform|Experimental|Repository catalog, dependency resolution and verified package downloads|Titan Store foundation; target download acceptance remains pending and no finished-storefront claim is made.
T8|Theme engine|Source|Packaged scene/keyframe themes with transitions, idle loops and audio|More than existing OPL theme images, BGM and built-in animations.
B2|Media tools|Claimed / source|General-purpose console music player|Separate from RiptOPL background music playback.
B3|Media tools|Claimed / source|General-purpose image and font viewers|Separate from rendering game artwork and UI fonts.
B4|System tools|Claimed / source|Integrated text/code editor and terminal|BoliviaOS tool suite, outside normal game launching.
B7|Media tools|Claimed / source|Integrated PDF viewer|A separate document-viewing application in the console shell.
R1,TV3|Emulator frontend|Source / claim|Retro-system ROM libraries with configured emulator/core launch|RETROLauncher and the Retro Arcade suite provide ROM catalogs beyond RiptOPL's PS1/PS2/Apps views; launching an emulator ELF through Apps already exists.
TV4|Emulator frontend|Claimed release|Retro Arcade launch-mode picker and return to the selected ROM|The suite documents 240p/480i/480p selection and returning to the same game; not a new PS2 OPL/Neutrino compatibility mode.
PX3,PX4|PS1 runtime|Experimental|Select PSXCore as a third PS1 runtime / use its source-buildable adapter|RiptOPL ships POPStarter and Ember, not PSXCore. Main no longer ships tester sources; the tester branch is separate.
PX1|PS1 runtime|Experimental|Optional guarded decoded-instruction code validation|A PSXCore mechanism; different from RiptOPL checking file/module identities before launch.
PX2,PX31,PX32|PS1 runtime|Experimental|PSXCore GPU/GTE/DMA semantic corrections|Includes palette/query fixes, signed INTPL interpolation and parked-worker GP1 DMA-control changes. No inferred superiority for a particular game.
PX5,PX33|PS1 runtime|Experimental|PSXCore MDEC/RGB24/buffered-interlace corrections|Includes publishing the completed interlace display descriptor; not proof that all FMVs are fixed.
PX6|PS1 runtime|Experimental|PSXCore SPU, capture-IRQ, reverb and CDDA corrections|Alternative runtime implementation, not a claim RiptOPL has no PS1 audio.
PX7,PX34|PS1 runtime|Experimental|PSXCore guest-memory, CPU-timing and load-delay fast paths|Includes precomputed addressing and smaller DMA/GP0/GP1 saves now enabled by default, with disable switches retained.
PX8,PX14|PS1 runtime|Experimental|PSXCore firmware-identity and transactional runtime-patch planner|Includes byte guards, overlap/capacity checks and revision-specific license-string changes; no generic region-bypass claim.
PX9,PX29|PS1 runtime|Experimental|PSXCore native-save worker, PFS ownership and flush guards|Partially provisioned native-partition path; source mechanisms do not establish power-loss durability or a complete APA user flow.
PX10|PS1 runtime|Experimental|PSXCore disc/TOC fingerprint binding to save identity|A content-identity mechanism beyond ordinary file naming.
PX11|PS1 runtime|Experimental|Optional adaptive PCM output-rate feedback|Off by default, changes rate/possibly pitch; not a CPU-speed fix.
PX24|PS1 runtime|Experimental|PSXCore bounded sector-tail cache and seek-status correction|Runtime I/O mechanism; broad game-speed improvement is unmeasured.
PX25|PS1 runtime|Experimental|PSXCore exact raster/polygon-cost fast path|Keep timing/compatibility evidence separate from build success.
PX26|PS1 runtime|Experimental|PSXCore GP0 packet/callback/empty-flush fast paths|Source optimization, not a standalone proven end-user compatibility feature.
PX30|PS1 runtime|Experimental|PSXCore bounded aligned/unaligned upload-row copies|The newer branch streams rows with aligned quadword loads while retaining bounds.
PX23,PX35|PS1 runtime|Experimental|PSXCore boot/save-worker and patch-plan diagnostics|Current adapter also reports planner failures and increases its bounded capacity.
'''

gaps = []
mapped = {}
for line in SPEC.strip().splitlines():
    ids,scope,status,title,note = line.split('|')
    ids = ids.split(',')
    assert not set(ids) & mapped.keys(), ids
    urls = list(dict.fromkeys(u for key in ids for u in evidence[key]))
    gap = dict(number=len(gaps)+1,ids=ids,scope=scope,evidence=status,feature=title,assessment=note,sources=urls)
    gaps.append(gap)
    for key in ids:mapped[key]=gap['number']

reasons = {}
def exclude(keys, status, reason):
    for key in keys.split(','):reasons[key]=(status,reason)
exclude('CA1,CA6,CA7','Companion parity','Current PS2-Servers README explicitly has SQLite library, JSON import/export, online backups and guided setup; not a missing loader-core feature.')
exclude('CA2,CA3,CA4,CA5,RI4,OM1,OM2,SM1,O12,O14,O15,OH6,OH7,OH8,OH9,MA1,MA2,TV5,OR5,CF4','Companion / separate scope','Desktop authoring, server, or file-manager workflow. Retained in the inclusive register; compare exact PS2-Servers/Launchstation parity separately, not as a missing RiptOPL game-loader feature.')
exclude('H5,H6,H7,H8,H10,H12','Usable external companion','PC/phone client feature. RiptOPL can use the external client; source compatibility with alpha.19 still needs current console acceptance. An older recommendation/shortcut is a documentation/pinning lag, not proof of missing console capability.')
exclude('CO3,CO4,CO5,CO6,CF1,CF2,CF3,U1,OR3,OR4','Implemented / validate','Present in RiptOPL source, including an experimental default-Off Caduceus text card. Hardware acceptance and safe GS ownership are separate questions.')
exclude('LU16,LU17,LU18,LU19,LU22,LU30,LU31,LU32,PX15,PX17,PX20,TV6,TV10','Overlap / design alternative','RiptOPL already supports the broad capability. Distinct implementation or presentation does not establish missing functionality; retained for provenance.')
exclude('PX12,PX13,PX19,PX22,PX27','Developer API / design alternative','Prepared API, empty automatic-profile catalog, path-hash identity choice, inventory probe or build policy. Not a delivered unique game-loader feature; source retained.')
exclude('PX16,PX18,PX28,H9','Upstream limitation','Limitation/removal in the other project rather than a capability RiptOPL lacks.')
exclude('U9','Historical proposal','Closed unmerged upstream proposal; not a delivered feature.')
exclude('H4','Implemented correction','Current raParseChunkHeader consumes exactly one binary delimiter and tests all 256 leading bytes. The alpha.18 whitespace-loss fix is already present; a full 2679-address client/game session is still untested here.')
exclude('N2','Overlap / current source','configReadMulti(CONFIG_NETWORK) calls configReadLegacyIP when the normal network config is absent; udpfssupport.c passes the resulting ps2_ip to its module. Shared IPCONFIG fallback exists; exact on-console precedence still needs regression coverage.')
exclude('O8,S1,H13,DT6','Fix / equivalence investigation','Keep driver/VRAM/memory-footprint correctness leads separate from feature counts. H13 is a concrete source delta (+0x1000 TX descriptor base); runtime causality/porting must be audited. DT6 release notes admit an unresolved debug FMV freeze.')
exclude('LU36','Unbundled implementation candidate','SPU2 ADPCM hardware-loop source landed on the luna frontend branch during this audit, after the wrapper-pinned frontend revision. Existing BGM is present; inspect performance/format tradeoffs separately.')

missing = set(allrows)-set(mapped)-set(reasons)
assert not missing, f'Unclassified IDs: {missing}'
assert not set(mapped)&set(reasons), 'Every ID has exactly one disposition'

dispositions = []
for key,row in allrows.items():
    if key in mapped:
        g=gaps[mapped[key]-1]; state='Consolidated #'+str(g['number']); reason=g['assessment']
    else:state,reason=reasons[key]
    dispositions.append(dict(**row,current_status=state,reason=reason,sources=evidence[key]))

def write_json(name,obj):
    (ROOT/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
write_json('consolidated-gaps.json',gaps)
write_json('id-dispositions.json',dispositions)

def mdcell(s):return str(s).replace('|','\\|').replace('\n',' ')

intro=f'''# Fork-gap refresh — October 21, 2026

Comparison target: [RiptOPL rebuild/main@{RIP[:8]}]({GH}NathanNeurotic/Open-PS2-Loader/tree/{RIP}). This report updates the [previous audit page]({GH}NathanNeurotic/Open-PS2-Loader/blob/{SITE}/fork-gaps.html), whose broad baseline was October 8 UTC and supplements were October 15 and October 19. The local working checkout was older (`2082cac3`); source comparisons below use the fetched target, not that checkout.

**One list of remaining differences:** the final table contains {len(gaps)} deduplicated capability rows across the surveyed console-loader ecosystem. It includes optional UI policies, partial parity, closed-source release claims, historical source and experimental runtime mechanisms, each labelled. It is not {len(gaps)} missing proven game features and not a roadmap. All {len(OLD)} original register IDs plus {len(NEW)} new IDs have a disposition; implemented overlaps, desktop companions, abandoned plans and upstream limitations are retained separately and do not inflate this list.

The live sweep queried **128 GitHub repository URLs/identities** (126 canonical repositories after the two duplicate aliases), plus their latest release lists. It follows the explicitly maintained RA, wOPL, uOPL and other known feature branches, and separately checks newer release tags and LUNA's pinned submodules. Most older repositories retain exactly the previously cited revision. This does not enumerate every branch or newly created fork on GitHub. Non-GitHub references were opened where accessible; PS2-Home links and OPL Manager were inaccessible, so no claim of fresh source coverage is made for those pages. The checked revisions are a frozen snapshot, not a moving promise.

No PS2 software was run, no games were launched, and no physical-console acceptance was performed. Existing upstream hardware reports are attributed, not reproduced. Code, build claims, screenshots and release notes are separate evidence levels. Unchanged external commits preserve their historical source evidence; absence/equivalence is reassessed against the current RiptOPL source surface, with unresolved cases labelled instead of guessed.

## Updates since the relevant earlier baselines

| Project | Earlier baseline → checked source/release | What changed and what it means |
|---|---|---|
| PS2TVCRT / FastLoader / Retro Volt Suite | Previously omitted → `42c33b5b`, FullAnFinalRelease published October 21 07:56 Pacific | Release describes FastLoader 2.1.1, Retro Arcade 1.1.0 and Windows suite. README still calls itself 2.0.8 and inconsistently names ELF versions. Recursive arbitrary-folder ISO scan, coordinated rename, Ember disc picker, embedded file manager and retro-ROM suite are tracked. Source is closed: capabilities are author/release claims, not inspected implementations. Only one repository commit since October 8 was returned, and it changes README layout; release functionality must not be dated from that commit. |
| xeRAbora | alpha.18 `0e5d35a3` → alpha.19 `28c6531c` | Four client-wrapper commits: ARM64 Linux package, OPL gitlink update, version and UI source sync. OPL RA `a9f97397` adds suffix marks and a smaller unframed cover mark. Alpha.18's watch-list whitespace fix already exists in RiptOPL; its hardcore/date, TV-flash toggle, rich-presence and list/grid changes are client features available through that companion. RiptOPL's alpha.17 recommendation is stale and needs a verified version-policy update. |
| RIPPS2 | `e8f317b2` → `e6b3fc9a`, v1.1.0-beta / build 110 | 24 commits. Build 104 adds Arabic/Persian shaping and bidi/Lao layout; 105 implements disc ripping; 106 adds in-game power off and row decoration controls; 107 implements file search; 108 adds RIPSHOT and silent default-on in-game menu; 109-110 add cached lists, pad-friendly scans and typed Save Settings To. Builds 105-108 are no longer plans. Host/PCSX2 evidence and published betas do not establish save safety on all hardware. RiptOPL #1017 already guards printf placeholders, so that subfeature is no longer a RI5 gap. |
| LUNA | `4614b0c5` → `f3c765e2` | Seven wrapper commits. Frontend moves `127d012b` → `3ec0d650`: retry USB boot lookup across volumes and defer MX4SIO fallback. PSXCore pin advances to `0d4348ea`. v3.1.3 reports working starting-disc/native swap behavior; preserve that as an upstream report, not our console result. |
| LUNA frontend branch | wrapper pins `3ec0d650`; branch also contains `1580671b` | One newer, not-wrapper-pinned change replaces ambient audio playback with SPU2 ADPCM hardware looping. It appeared during the sweep; preserve separately as LU36 rather than misrepresent it as already bundled. |
| PSXCore | public `66c70e9f` → `0d4348ea` | Eleven commits: bounded quadword upload copies, parked-worker GP1 DMA control, interlace descriptor publication, signed INTPL correction, planner capacity/diagnostics and default-enabled addressing/DMA/GP0/GP1 save optimizations. Main removes standalone tester/inventory sources in favor of the tester branch even though README still describes them; code and packaging are authoritative. No inferred full-speed/full-compatibility claim. |
| OPL-DS4RTBT | default `e016d934` unchanged; release rt-2.7.0 → `2cf30851` | Eighteen commits beyond the default head: per-slot mixed physical/wireless routing, split two-port polls, earlier single driver startup, disconnect RPC and reorganized controller screens. This was missed by checking only the default branch. Release notes also describe a KH2 SMB+PADEMU memory correction with an unresolved debug FMV freeze; retain as a bounded investigation, not a proven universal fix. |
| Upstream OPL | `4cc74baa` → `b3a21997` | Four commits, all documentation/contribution guidance. No new runtime feature in this range. |
| OPLattice / OPHTML / ORBIT / Caduceus / Extended APA / PS2CF / DualSense-BT / PS2-Launcher / Modulo / sOPL / uOPL / RRVE / Titan | Same known source heads | No new source delta at the checked branches; existing qualified gaps remain. Historical modular PADEMU is explicitly `modularPademu@66b93542`, not its unrelated master. |
| PSBBN Definitive Project | three commits since October 8 → `59992562` | Application-database changes, not new loader runtime mechanisms. RiptOPL #1023 already updates its PSBBN Flow presentation; orbital/grid renderers remain separate gaps. |
| wLaunchELF R3Z | v4.80 / `06b06d00` | Neutrino ISO launch, MMCE VMC switching and RetroGEM signalling, Ember launch, configurable core support and sorting. These are file-manager/launcher extensions; much of the game-loader function already exists in RiptOPL. |
| DKWDRV | 1.7.6s / `7f41569e` | USB reset/OHCI initialization and drawing fixes; physical PS1 launch integration remains DL1, not another duplicated generic PS1 gap. |
| Okeanos86 BDMAssault | unchanged default `68731fca`; Alpha release October 11 | Release publishes read-only POPStarter UDPFS fallback. RiptOPL already includes a UDPFS PS1 path; release publication is not new missing transport support. |
| Odyssey Launcher | v0.18.0 / `f935f07f` | New layouts, models, theme downloader, update checks and media work. It runs on Windows/Godot and launches PC emulators; it is not a PS2-native loader. Keep as design inspiration, outside the console gap count. |
| PS2 Webcore Launcher | 2.1.0 / `2526ef64` | Windows-x64 controller/patch updates, not a console loader. Its previous directory classification needed correction. |
| Own companion repositories | PS2-Servers `42c0613b`, Launchstation `593f16dc`, POPSLoader 1.3.1, launcHER `94809b18` | These progressed too. Library/setup/backups, file management and PS1-core overlap must not be represented as capabilities absent from the entire ecosystem merely because not embedded inside RiptOPL. |

## Corrections and open investigations

- H4 is already implemented in `src/ranet.c`: parse `RAC1` through `%n`, verify exactly one delimiter, then copy binary bytes. The production host test covers every possible leading byte, exact lengths/counts and the 20 KiB bound. It does not reproduce the 2,679-address hardware session.
- H13 is a separate real source difference: upstream `SMAPSendPacket` adds `0x1000` to the TX descriptor pointer; current RiptOPL `modules/network/smap-ingame/xfer.c` does not. Do not conflate this with the fixed menu watch-list parser. Audit the applicable SMAP buffer contract and test the actual launch path before porting it.
- CO4 is present as an explicit experimental default-Off Caduceus title/points card. It should not still be counted as absent; safe GS ownership is still unresolved.
- PC CARD CF, parental launch lock, console achievement browsing, Mode 6 telemetry, PS1 POPStarter RA and Neutrino RA are present in source with their existing scope/acceptance limits.
- LU18 is overlap: RiptOPL already exposes global and per-game Neutrino `-logo` arguments, including documented backend suppression. It does not lack a per-title startup-logo setting.
- RI5 now means keyed version-tolerant packs and layered font behavior; RiptOPL already validates unsafe printf conversions after #1017. RI9 separately tracks actual shaping/bidi/Lao differences.
- N2 is also an overlap at the source-contract level: `configReadMulti` falls back to `configReadLegacyIP` when network settings are absent, and UDPFS module initialization consumes `ps2_ip`. The old claim that RiptOPL lacks shared IPCONFIG reuse was too broad; console precedence regression coverage remains separate.
- O8 (VRAM budget clamp), S1 (DRDY strategy) and DT6 (KH2 IOP footprint) remain bounded equivalence/regression investigations. A different implementation is insufficient proof of a currently failing user feature.
- External xeRAbora alpha.19 adds an ARM64 package; that is usable companion distribution, not a reason to fork the console protocol or count all client UI features as missing RiptOPL features.

## Evidence and coverage files

- `repository-heads.json`: 128 repository queries, exact SHA/date, canonical redirects and prior evidence refs. Some directory entries had no previous SHA, so their deltas are bounded by the audit date rather than a fabricated old revision.
- `releases.json`: latest release query for each repository, with tag, publication time and body. Mutable release tags are called out where relevant.
- `id-dispositions.json`: every old and new stable ID, its current disposition and evidence links. No ID is reassigned or silently dropped.
- `consolidated-gaps.json`: machine-readable version of the single list below. Source links point to existing detailed evidence; unchanged historical source evidence retains its original date.
- `comparison-summary.json`: exact ranges and changed file/commit names for focused comparisons, plus the snapshot boundaries.

External-page limits: E2OPL still reports its 2015 update; PSUManager's latest visible change is September 14. BoliviaOS continues to advertise Beta 1.0 integrated tools. POPStarter, XEB+, FunTuna and OpenTuna resource pages were read, but full forum histories were not exhaustively crawled. Nine PS2-Home resources and OPL Manager failed retrieval. No newly delivered feature is inferred from an unread page, and those references remain explicitly unrefreshed.

## Single consolidated list of remaining console-loader differences

This is the one deduplicated list. **Source** means an implemented source capability missing as an equivalent integrated RiptOPL capability; it does not mean hardware validated. **Partial** identifies the exact additional scope. **Claimed release** means closed-source/public-description evidence. **Experimental**, **Historical source**, **Design option** and **Needs validation** must not be read as proven current game defects. Desktop-only companion records and fix leads remain in the inclusive dispositions, not mixed into this table.

| # | Capability | Scope / evidence | Stable IDs | Exact missing portion and limits | Sources |
|---|---|---|---|---|---|
'''

table=''
for g in gaps:
    links=', '.join(f'[source {i+1}]({u})' for i,u in enumerate(g['sources'][:4]))
    table += '| '+' | '.join(mdcell(x) for x in [g['number'],g['feature'],g['scope']+' / '+g['evidence'],', '.join(g['ids']),g['assessment'],links])+' |\n'
(ROOT/'FORK-GAPS-2026-10-21.md').write_text(intro+table,encoding='utf8')

write_json('releases.json',LIVE['releases'])
write_json('repository-heads.json',LIVE['heads'])

old_deltas=json.loads((ROOT/'deltas.json').read_text(encoding='utf8'))
comparisons={}
for key,d in {**old_deltas,**LIVE['deltas']}.items():
    if isinstance(d,dict) and ('total_commits' in d or 'files' in d):
        comparisons[key] = dict(status=d.get('status'),total_commits=d.get('total_commits'),base=d.get('base_commit',{}).get('sha'),merge_base=d.get('merge_base_commit',{}).get('sha'),commits=[dict(sha=c['sha'],message=c['commit']['message']) for c in d.get('commits',[])],files=[f['filename'] for f in d.get('files',[])])
write_json('comparison-summary.json',dict(date='2026-10-21',riptopl=RIP,site=SITE,github_sweep_utc='2026-10-21T15:34:55Z to 2026-10-21T15:35:15Z',later_frontend_branch='1580671bab32d124cc6affaac3a3251d515b4664',comparisons=comparisons))

def esc(x):return html.escape(str(x),quote=True)
gap_table='<table><thead><tr><th># / IDs</th><th>Missing capability</th><th>Scope / evidence</th><th>Boundary</th></tr></thead><tbody>\n'
for g in gaps:
    links=' · '.join(f'<a href="{esc(u)}">source {i+1}</a>' for i,u in enumerate(g['sources'][:3]))
    gap_table+=f'<tr><td>{g["number"]}<br><code>{esc(", ".join(g["ids"]))}</code></td><td>{esc(g["feature"])}<br>{links}</td><td>{esc(g["scope"])}<br>{esc(g["evidence"])}</td><td>{esc(g["assessment"])}</td></tr>\n'
gap_table+='</tbody></table>'
section=f'''<section class="fork-gap-section" aria-labelledby="oct21-delta">
<h2 id="oct21-delta">October 21, 2026 — broad freshness sweep and reconciled list</h2>
<p>Compared with <a href="{GH}NathanNeurotic/Open-PS2-Loader/tree/{RIP}">RiptOPL <code>{RIP[:8]}</code></a>. Queried 128 GitHub repository URLs (126 canonical repositories) and their latest releases. The old broad baseline is October 8; October 15/19 were supplements. Existing historical evidence is preserved. <b>All {len(OLD)} old IDs and {len(NEW)} new IDs now have a disposition; the {len(gaps)} rows below are deduplicated differences, not a count of missing proven game features.</b></p>
<p><a href="audit/2026-10-21/FORK-GAPS-2026-10-21.md">Full dated audit and single list (Markdown)</a> · <a href="audit/2026-10-21/repository-heads.json">Exact repository revisions</a> · <a href="audit/2026-10-21/releases.json">Release sweep</a> · <a href="audit/2026-10-21/id-dispositions.json">Every ID disposition</a> · <a href="audit/2026-10-21/consolidated-gaps.json">Deduplicated list (JSON)</a></p>
<ul>
<li><b>FastLoader / Retro Volt:</b> the newly added <a href="https://github.com/Kyllemn/PS2TVCRT/releases/tag/FullAnFinalRelease">October 21 release</a> describes FastLoader 2.1.1, Retro Arcade 1.1.0 and a Windows suite. README version text is older. Recursive ISO scanning, coordinated renaming, an Ember disc picker and a retro-ROM launcher are release claims: the source is closed.</li>
<li><b>xeRAbora alpha.19:</b> Linux ARM64 distribution and RA mark placement/cover changes. Alpha.18's binary-whitespace watch-list bug is <b>already fixed in RiptOPL</b>. The in-game SMAP descriptor-base change is a separate source-fix candidate, not a new feature. Alpha.17 recommendations need version-policy review; PC-client options are not missing console-core features.</li>
<li><b>RIPPS2 build 110:</b> RIPDISC, file search and RIPSHOT have moved from plans to released source. New bidi/shaping/Lao text, cached per-source lists, typed settings picker, paused-menu power off and row-decoration controls are tracked. RiptOPL now already guards malformed printf conversions.</li>
<li><b>LUNA / PSXCore:</b> seven wrapper and eleven core commits since their last relevant pins. USB boot probing is fixed; graphics/timing/save mechanisms are extended. PSXCore main now moves tester/inventory applications to the tester branch. A newer SPU2 ADPCM-loop frontend commit is not yet wrapper-pinned.</li>
<li><b>OPL-DS4RTBT:</b> default branch stayed at <code>e016d934</code>, but <a href="https://github.com/MiguelQueiroz010/OPL-DS4RTBT/releases/tag/rt-2.7.0">rt-2.7.0</a> is 18 commits ahead, including mixed real/wireless multitap routing and new controller management. Its KH2 debug FMV freeze remains unresolved.</li>
<li><b>Overlap corrections:</b> Caduceus's experimental unlock card, PC CARD CF, parental lock, per-title logo controls and console achievement browsing are present. Upstream OPL's four new commits are documentation-only. Odyssey and PS2 Webcore are Windows frontends, not PS2-native game loaders.</li>
</ul>
<p>Source, published-release claims, host/emulator evidence and physical-console acceptance are separate. No console testing was performed in this audit. Inaccessible PS2-Home/OPL Manager references remain explicitly unrefreshed; this sweep does not enumerate every branch or every fork on GitHub.</p>
<h3 id="consolidated-missing">Single consolidated list of remaining differences</h3>
<p>One row per capability family. Source implementations, partial parity, historical code, design alternatives, experimental runtime mechanisms and closed-source claims are labelled. Desktop tools, upstream limitations, unshipped APIs and correctness investigations remain in the inclusive register/disposition file without inflating the console capability count.</p>
{gap_table}
</section>
'''
page=BASE.read_text(encoding='utf8')
page=page.replace('<h2 id="oct19-delta">','<h2 id="oct19-delta">',1)
marker='<section class="fork-gap-section" aria-labelledby="oct19-delta">'
assert marker in page
page=page.replace(marker,section+'\n'+marker,1)
page=page.replace('<a href="#oct19-delta">October 19 findings</a>','<a href="#oct21-delta">October 21 findings</a>\n<a href="#consolidated-missing">Single missing-capability list</a>\n<a href="#oct19-delta">Historical October 19 findings</a>',1)
page=page.replace('subsequent merges can change whether a gap remains open.','subsequent merges can change whether a gap remains open. The October 21 reconciliation and single list above the historical sections supersede older status wording.',1)
page=page.replace('<strong>184</strong>','<strong>'+str(len(allrows))+'</strong>',1)
page=page.replace('<strong>33</strong>','<strong>34</strong>',1)
page=page.replace('<strong>144</strong>','<strong>145</strong>',1)
page=page.replace('<strong>9</strong>','<strong>11</strong>',1)
page=page.replace('Integrated records, retained with hardware-verification caveats','Implemented records, retained with hardware-verification caveats',1)
page=page.replace('The October 15 supplement added PS2CF and other derivatives.','The October 21 sweep supersedes earlier status statements; see the dated findings and consolidated list. The October 15 supplement added PS2CF and other derivatives.',1)
sources_pos=page.index('<h2 id="sources">')
sources_end=page.index('</tbody>',sources_pos)
tvsource='<tr><td><code>TV</code></td><td><a href="https://github.com/Kyllemn/PS2TVCRT">FastLoader / Retro Volt Suite (PS2TVCRT)</a></td><td>Closed-source Neutrino/Ember frontend and Retro Arcade suite; release claims</td><td>10</td></tr>\n'
page=page[:sources_end]+tvsource+page[sources_end:]
prefix_counts=collections.Counter(re.match(r'[A-Z]+',k)[0] for k in allrows)
source_start=page.index('<h2 id="sources">')
source_stop=page.index('</table>',source_start)
source_html=page[source_start:source_stop]
for prefix,count in prefix_counts.items():
    pattern=r'(<tr><td><code>'+prefix+r'</code></td>(?:(?!</tr>).)*<td>)\d+(</td></tr>)'
    source_html=re.sub(pattern,lambda m:m[1]+str(count)+m[2],source_html,flags=re.S)
page=page[:source_start]+source_html+page[source_stop:]

def filter_state(key):
    if key in mapped:
        status=gaps[mapped[key]-1]['evidence'].lower()
        return 'partial' if status=='partial' else 'experimental' if status=='experimental' else 'historical' if status=='historical source' else 'tracked'
    status=reasons[key][0].lower()
    if status.startswith('implemented'):return 'shipped'
    if status.startswith(('overlap','companion parity','usable')):return 'overlap'
    if status.startswith('companion'):return 'companion'
    if status.startswith('upstream limitation'):return 'limitation'
    if status.startswith('historical'):return 'historical'
    if status.startswith('unbundled'):return 'experimental'
    return 'candidate'

# Update the searchable register without rewriting the page's original formatting.
for d in dispositions:
    key=d['id']
    pat=r'(<tr data-filter-value="[^\"]+"><td><code>'+re.escape(key)+r'</code></td>.*?</tr>)'
    m=re.search(pat,page,re.S)
    if not m:continue
    if key in mapped:
        label='See consolidated #'+str(mapped[key]);state=filter_state(key)
    else:
        label=reasons[key][0];state=filter_state(key)
    row=re.sub(r'<span class="fork-gap-state" data-state="[^\"]+">.*?</span>',f'<span class="fork-gap-state" data-state="{state}">{esc(label)}</span>',m[1],flags=re.S)
    row=re.sub(r'^<tr data-filter-value="[^\"]+">',f'<tr data-filter-value="{state}">',row)
    page=page[:m.start()]+row+page[m.end():]

# Append the new stable IDs to the existing six-column searchable register.
start=page.index('<h2 id="at-a-glance">')
end=page.index('</tbody>',start)
newhtml='\n'
for key,title,project,status,url in NEW:
    d=next(x for x in dispositions if x['id']==key)
    label='See consolidated #'+str(mapped[key]) if key in mapped else reasons[key][0]
    state=filter_state(key)
    newhtml+=f'<tr data-filter-value="{state}"><td><code>{key}</code></td><td>{esc(title)}</td><td>October 21 delta</td><td><a href="{esc(url)}">{esc(project)}</a></td><td>{esc(status)}</td><td><span class="fork-gap-state" data-state="{state}">{esc(label)}</span></td></tr>\n'
page=page[:end]+newhtml+page[end:]

# Add the previously omitted project and correct the PC-only directory identities.
directory=BeautifulSoup(page,'html.parser')
dh=directory.find(id='project-directory')
dt=dh.find_next('table')
assert dt
existing=dt.find('tbody')
tvrow='<tr data-filter-value="Game loaders"><td><a href="https://github.com/Kyllemn/PS2TVCRT">FastLoader / Retro Volt Suite (PS2TVCRT)</a></td><td><span class="directory-tag">Game loaders</span></td><td>Release claims; closed source</td><td>CRT-focused Neutrino/Ember frontend, integrated file manager and Retro Arcade suite; TV1–TV10</td></tr>'
# Locate the original directory table in raw HTML, preserve everything else.
dp=page.index('<h2 id="project-directory">')
de=page.rfind('<tr',dp,page.index('id="catalog-F"',dp))
tvrow=tvrow.replace('<tr data-filter-value="Game loaders">','<tr data-filter-value="Game loaders" id="catalog-F">',1)
page=page.replace(' id="catalog-F"','',1)
page=page[:de]+tvrow+'\n'+page[de:]
for name in ['OdysseyLauncher','PS2-Webcore-Launcher']:
    pat=r'<tr data-filter-value="[^\"]+">(?:(?!</tr>).)*https://github.com/[^\"]*/'+name+r'(?:(?!</tr>).)*</tr>'
    m=re.search(pat,page,re.S)
    if m:
        row=m[0]
        row=re.sub(r'data-filter-value="[^\"]+"','data-filter-value="Tools &amp; themes"',row,count=1)
        row=re.sub(r'<span class="directory-tag">.*?</span>','<span class="directory-tag">Tools &amp; themes</span>',row,count=1)
        row=row.replace('</tr>','</tr>')
        # Replace the descriptive cell only.
        cells=list(re.finditer(r'<td>.*?</td>',row,re.S))
        if len(cells)>=4:
            c=cells[-1];row=row[:c.start()]+'<td>Windows frontend for PC/emulator use; not a PS2-native loader. October 21 classification correction.</td>'+row[c.end():]
        page=page[:m.start()]+row+page[m.end():]

page=page.replace('data-filter-value="Tools &amp;amp; themes"','data-filter-value="Tools &amp; themes"')
page=page.replace('data-filter-value="PS1 &amp;amp; disc"','data-filter-value="PS1 &amp; disc"')
(ROOT/'fork-gaps.html').write_text(page.rstrip()+'\n',encoding='utf8')
print(json.dumps(dict(old=len(OLD),new=len(NEW),register=len(allrows),consolidated=len(gaps),excluded=len(reasons)),indent=2))
