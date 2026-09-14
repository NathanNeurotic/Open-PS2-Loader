# RFC: Extended APA (>2 TiB) Storage Architecture for Open PS2 Loader

## Status: Proposed / Banked for Staged Implementation
**Branch Reference:** `extended-apa` (`https://github.com/L10N37/Open-PS2-Loader-Extended-APA`)  
**Target Subsystems:** `modules/hdd/xhdd`, `modules/hdd/apa`, `modules/hdd/hdl`, `modules/iopcore/cdvdman`

---

## 1. Executive Summary
The PlayStation 2's native APA (Adapted Partition Architecture) disk partitioning scheme was designed around 32-bit sector addressing. With standard 512-byte Logical Block Addressing (LBA), the maximum addressable storage capacity is:
\[
2^{32} \times 512 \text{ bytes} = 2{,}199{,}023{,}255{,}552 \text{ bytes} \approx 2.0 \text{ TiB}
\]
Modern hard drives and SATA SSDs installed via aftermarket network adapters regularly exceed 2 TiB (e.g., 4 TiB, 8 TiB, up to 16 TiB). The `Open-PS2-Loader-Extended-APA` project developed by L10N37 overcomes this hard ceiling by introducing banked APA partitioning, 64-bit sector translation, and an optimized games table.

This RFC details the architectural changes required to safely adopt Extended APA into Open PS2 Loader without compromising stability for users with standard $\le 2\text{ TiB}$ drives.

---

## 2. Core Technical Architecture

### 2.1 64-Bit Devctl and LBA Translation
In the standard PS2SDK APA driver:
- `apa_header_t` and `hdl_game_info_t` track partition start sectors, lengths, and layer breaks using unsigned 32-bit integers (`u32`).
- The devctl and disk IO interfaces communicate with the ATAPI controller via 28-bit or 48-bit LBA registers.

**Extended APA Modifications:**
- Upgrades internal sector types to 64-bit integers (`u64`) across `xhdd.irx`.
- Introduces disk banking: the total disk capacity is divided into 2 TiB addressable banks.
- Bank selection is managed transparently when dispatching reads/writes across sector boundaries.

### 2.2 Header Layout & Partition Chaining
Extended APA maintains backward compatibility at the root of the disk:
1. **Bank 0 (0 to 2 TiB):** Formatted with standard APA header (`__mbr`), partition chains, and standard system partitions (`__net`, `__system`, `__common`).
2. **Bank $N$ ($> 2$ TiB):** Contains an extended APA marker and linked partition tables.
3. If an older tool or non-extended OPL ELF accesses the drive, it sees Bank 0 as a valid 2 TiB APA drive without corrupting beyond-2TiB data, provided it does not attempt an out-of-bounds write.

### 2.3 $O(1)$ Game Indexing (`games_banked.bin`)
On a 4 TiB–16 TiB drive, a user may store 1,000+ PS2 DVD/CD images.
- Standard OPL traverses the APA partition chain sequentially on HDD initialization. Walking 1,000+ partition headers via IOP IDE/SATA transfers can take 30–60 seconds, freezing the UI.
- Extended APA introduces a pre-indexed partition database (`games_banked.bin` / cached TOC).
- Reading a single contiguous index file on boot reduces HDD population time to under 1 second ($O(1)$ lookup).

---

## 3. Scope & Risk Analysis

| Component | Nature of Change | Risk Level | Mitigation |
|---|---|---|---|
| `modules/hdd/xhdd` | 64-bit sector math, banked APA traversal | High | Dual-mode driver: test for Extended APA magic; fallback to standard APA code path for $\le 2\text{ TiB}$. |
| `modules/iopcore/cdvdman` | Sector translation for ISO read commands $> 2\text{ TiB}$ | Critical | Extensive verification with physical discs / virtual sectors to ensure zero regression on standard drives. |
| `src/hdd.c` / `src/hddsupport.c` | UI game listing, VMC partition allocation | Medium | Ensure VMC partitions remain constrained within Bank 0 unless explicitly relocated. |
| External PC Tooling | Formatting and installing games $> 2\text{ TiB}$ | High | Document compatibility with specialized HDL Dump / HDL Batch installer branches supporting Extended APA. |

---

## 4. Phased Implementation Roadmap

### Phase 1: SDK & IOP Driver Harmonization
- Import extended APA structures from `L10N37` into `common/` and `modules/hdd/`.
- Validate that standard 2 TiB drives boot, list games, and launch ISOs with zero behavioral difference.

### Phase 2: Game Loading Above 2 TiB
- Update `cdvdman` HDD backend to translate LBA calls $> 2^{32}-1$ using the banked sector offset.
- Verify game boot on physical SATA test setups with 4 TiB and 8 TiB drives.

### Phase 3: Fast TOC & OPL UI Integration
- Support loading `games_banked.bin` if present on `hdd0:__common/` or `hdd0:__system/`.
- Provide on-console partition integrity validation tool.
