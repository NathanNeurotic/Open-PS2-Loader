# exFAT storage: setup, benefits and limits

RiptOPL can read games stored as files on an exFAT volume, including an internal ATA HDD. **MBR and GPT are supported partition-table choices for the internal exFAT HDD.** The filesystem, partition table and game layout are separate decisions: GPT does not make a missing `DVD` folder appear, and enabling APA does not select the exFAT game list.

## Choose the layout

| Layout | Where PS2 games live | Source to enable |
|---|---|---|
| Internal HDD, exFAT with MBR | `CD/` and `DVD/` files | BDM and Internal HDD (exFAT) |
| Internal HDD, exFAT with GPT | `CD/` and `DVD/` files | BDM and Internal HDD (exFAT) |
| Internal HDD, APA/HDLoader | Installed game partitions | HDD (APA) |

MBR with 512-byte logical sectors has the conventional approximately 2 TiB addressing limit. GPT permits partition addresses beyond that limit; this is not a guarantee that every disk capacity, adapter or partition layout has been tested. Neither choice changes the speed of the ATA connection. A supported hybrid APA/exFAT layout can expose both sources, but constructing one is an advanced partitioning task, not a requirement for ordinary exFAT use.

**GPT/exFAT is enabled through BDM; it is not blocked by the APA safety check.** RiptOPL registers both MBR and GPT partition drivers. Selecting the separate HDD (APA) source does not make a GPT/exFAT volume an APA disk. This follows the distinction in [grimdoomer's large-capacity HDD implementation](https://github.com/grimdoomer/Open-PS2-Loader/blob/d1f51be4452074c2352931e0b9c474da9242e481/src/hddsupport.c): GPT/exFAT uses the block-device path, while the APA/PFS stack is skipped for non-APA media.

Use a disk exposing **512-byte logical sectors**. A 512e disk has 4 KiB physical sectors but presents 512-byte logical sectors and is acceptable. A 4Kn disk presents 4096-byte logical sectors and is unsupported. Back up existing files before formatting or changing the partition table; conversion is not a troubleshooting step for an empty game list.

## Set up an internal exFAT HDD

1. Create an MBR or GPT partition table and an exFAT volume on your PC. Use the formatter's **Default** allocation-unit size.
2. Create `DVD` and `CD` at the volume root. Put DVD game images in `DVD/` and CD game images in `CD/`. For example, `DVD/SLUS_203.12.Game Name.iso` follows the established OPL naming format. Keep the complete image rather than splitting it for FAT32's file-size limit.
3. In **Settings → Game Sources**, enable **BDM Devices Start Mode** and **Internal HDD (exFAT)**. The separate **HDD (APA) Start Mode** controls APA game partitions; it is not required to enumerate a plain exFAT disk.
4. Leave **BDM Prefix Path** empty when `CD/` and `DVD/` are at the root. A prefix of `OPL` instead searches `OPL/CD/` and `OPL/DVD/`. The prefix applies to BDM sources, so check its effect on other attached devices too.
5. Open the HDD (exFAT) BDM game list. The default startup page only chooses which list opens first; it does not move games between the APA and BDM lists. Save settings when the setup is correct.

The internal exFAT HDD mounts into the shared `massN:` namespace. `mass0:` does **not** always mean USB: numbers depend on mount order. For a Neutrino custom path, the typed `ata:/neutrino/neutrino.elf` alias identifies internal ATA storage more reliably than a fixed slot number.

## Benefits and limitations

- **PC file management:** copy images and artwork as ordinary files rather than installing each PS2 game into an HDLoader partition. exFAT supports individual files larger than FAT32's 4 GiB limit.
- **Large-disk partitioning:** GPT removes MBR's conventional addressing limit. exFAT alone does not remove that limit from an MBR disk.
- **Game compatibility still depends on the core:** native OPL supports ISO, ZSO and UL layouts; Neutrino uses ISO. Changing the filesystem does not resolve every game's compatibility settings. See [Neutrino](NEUTRINO.md).
- **Fragmentation still matters:** native OPL shares a bounded 64-entry fragment table across image parts. Neutrino's BDM mapping budget includes the ISO and VMCs together. Copy files sequentially with adequate free space; a fresh copy can help, but deleting and recopying is not guaranteed to make a file contiguous.
- **VMCs have additional write constraints:** native OPL's FAT32/exFAT VMC backing must be contiguous. Neutrino supports multiple extents within its shared budget. Back up cards containing saves before attempting repairs. See [VMC creation and recovery](VMC.md).
- **Booting and loading games are different:** support for an exFAT game disk does not make that disk a FreeHDBoot/APA boot installation. Launch RiptOPL using an available boot method, then use its BDM list.
- **PS1 uses a separate runtime:** place VCDs in `POPS/` and use the matching BDMA exFAT setup for POPSTARTER. PS2 exFAT support alone does not install that runtime. See [VCD setup](VCD.md).

## APA-Jail: APA/PFS and exFAT on the same disk

**APA-Jail is a hybrid layout, not another filesystem or an option you enable in RiptOPL.** It lets APA/PFS storage for PSBBN/system data coexist with an exFAT area for game files and homebrew. The [PSBBN Definitive Project](https://github.com/CosmicScale/PSBBN-Definitive-Project) uses APA-Jail, developed by Berion. Use that project's installation tools and instructions to create or maintain its layout; ordinary PC repartitioning can destroy the APA side.

RiptOPL recognizes the supported **APA+MBR hybrid** by a valid, checksummed APA header plus an MBR FAT/exFAT partition entry beyond the APA reserved area. An MBR signature alone does not make a plain APA disk an APA-Jail disk.

| Disk layout | BDM FAT/exFAT access | APA/PFS access |
|---|---|---|
| Plain MBR/exFAT | Supported | Not an APA disk |
| Plain GPT/exFAT | Supported | Not an APA disk |
| Recognized APA+MBR/exFAT (APA-Jail) | Supported | Supported for a valid APA layout |
| Mixed GPT+APA metadata | GPT FAT/exFAT volumes still use BDM | Not implemented by the currently embedded APA driver |

The last row is an **APA-driver limitation, not a ban on GPT**. The current APA build uses the traditional APA journal/error-sector layout; a GPT-aware APA build needs a different layout. Its APA stack is skipped on GPT media, leaving BDM's GPT driver enabled. Do not remove that separation merely to force the APA page to open a GPT disk.

### Games and settings on APA-Jail

Games stored as files on the exFAT side belong in its `DVD/`, `CD/` and `POPS/` folders and appear through **BDM → Internal HDD (exFAT)**. The **HDD (APA)** list is for HDLoader game partitions; it does not list those exFAT files. RiptOPL may itself be launched from the APA side without moving the game files there.

For an APA launch on a recognized hybrid, RiptOPL normally adopts the mounted exFAT volume as its settings home:

- Existing RiptOPL settings on exFAT are preferred first.
- Otherwise, a **Custom Settings Path** saved in the APA data home keeps that explicit routing in force.
- Without that redirect, older RiptOPL settings in `+OPL` or `__common/OPL/` are read as carry-over settings. The next save writes to the exFAT home; this is not a destructive move or deletion of the old settings.
- On a first run, an official-OPL seed, or APA carry-over, the exFAT home enables the ATA BDM transport and starts a disabled BDM list on **Auto**. Once RiptOPL has saved its own settings there, your saved BDM start-mode choice is respected.

This depends on the exFAT volume mounting successfully. If it is not available during discovery, RiptOPL can use an accessible APA data home instead. Check the reported settings path and the actual volume before deleting configurations or assuming a save failed. RiptOPL's master file is `settings_riptopl.cfg`; official OPL's `conf_opl.cfg` is a separate file. Network, artwork, per-game files and other shared data still need their correct paths.

### Safety and troubleshooting

RiptOPL is not an APA-Jail partition manager. Its APA driver refuses partition-table modifications, and the ATA BDM write fence protects the first 128 MiB of an APA disk. Those guards do not validate every possible hybrid layout or make an overlapping partition safe. Back up valuable data, use the layout's own maintenance tools, and do not convert an installed APA-Jail disk to GPT or reformat it to fix an empty list.

For missing games, check the **exFAT BDM list**, its transport/start settings and prefix first. For missing settings, check which home was selected and whether an APA Custom Settings Path is present. **Code 402 is not an instruction to format.** See [APA safety and recovery](APA-SAFETY.md).

## HDD detected, but games missing

Check the game list and path before changing the disk:

1. Verify you are viewing the **BDM HDD (exFAT)** source, rather than the APA HDD source. Both use an HDD icon.
2. Check BDM start mode, the internal-HDD transport toggle, and **BDM Prefix Path**. An old configuration can point at a subfolder even when your files are at the root.
3. Check the actual `DVD/` and `CD/` contents, image names/extensions, and the selected PS2/PS1 view. A VCD in `POPS/` belongs in the PS1 view.
4. Refresh the source after applying settings. If the disk does not mount at all, check its partition/filesystem and sector size separately from game enumeration.
5. Record the exact build suffix, core, settings and unchanged disk layout when comparing builds. Back up your settings before trying a clean configuration; deleting all settings loses useful evidence and is not a required installation step.

The fixes in [PR #894](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/894) address a stale live BDM prefix after settings changes and an ATA readiness probe after the existing startup settle. Host tests demonstrate those defects and their fixes; they do not establish that either was the cause of every reported empty list, or replace a same-console test.
