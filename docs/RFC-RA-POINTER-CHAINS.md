# RFC: In-Game RetroAchievements Pointer Chains in ee_core

## Status: Proposed / Banked for Staged Implementation
**Branch Reference:** `xerabora/main` & `hacan-opl/ra` (commit `0c5f61a3`)  
**Target Subsystems:** `ee_core/src/ra.c`, `include/coreconfig.h`, `modules/network/common/ra_snap.h`, `modules/network/common/ra_watch.h`

---

## 1. Executive Summary
Open PS2 Loader currently incorporates RetroAchievements Phase 1 telemetry in `ee_core/src/ra.c`. During the vertical blank interrupt (`RA_OnVblank`), `ee_core` takes a snapshot of directly addressed memory locations and streams them via SIF DMA to the IOP `raudp` module, which packets them over UDP to a PC companion client (`xerabora`).

However, many complex PS2 titles (e.g., *Burnout 3*, *Tony Hawk's Underground*, *Need for Speed*, *Final Fantasy X*) locate player statistics, quest flags, or race states behind **dynamic pointer chains** (e.g., `[[BaseAddress + 0x14] + 0x8] + 0x30`). Because these pointers change dynamically across load screens, a static address watch list cannot track them.

Hacan359's experimental branch implements a directed acyclic graph (DAG) evaluator for pointer chains directly inside `ee_core`. This RFC defines the architecture, memory layout, safety constraints, and step-by-step plan to integrate pointer chain evaluation safely into OPL.

---

## 2. Core Constraints & Hardware Reality

### 2.1 Low-Memory Budget
- In `ee_core`, executable code and data must reside strictly below `0x00096E00` (less than 77 KiB total budget). If `ee_core`'s BSS or text sections expand beyond this boundary, it collides with game ELF load spaces, causing immediate crashes during retail game startup.
- Dynamic heap allocation (`malloc`/`free`) is completely forbidden inside interrupt context.

### 2.2 Unmapped Memory Traps
- During stage loading or scene transitions, pointer values in game RAM frequently hold uninitialized values (e.g., `0x00000000` or random unaligned garbage).
- Dereferencing an unmapped address or reading an odd address via multi-byte instructions raises a hardware exception (TLB Miss / Bus Error) in EE interrupt context, freezing the console.
- **Safety Rule:** Every step of pointer dereferencing must be clamped to the valid user RAM window (`RA_RAM_LOW = 0x00080000` to `RA_RAM_HIGH = 0x02000000`) and read byte-by-byte to eliminate unaligned access traps.

---

## 3. Data Structure Design

### 3.1 Node Representation
Pointer chain nodes are encoded as an array of compact structures (`struct ra_node`):
```c
struct ra_node {
    u32 w;      // Bitfield: [31] from_node flag, [30..28] size (1, 2, 4), [27..0] parent index
    u32 offset; // Static offset added to base pointer
};
```

### 3.2 Dual-Use Allocation inside `ra_watch`
Rather than dedicating a separate large BSS buffer in `ee_core`, the pointer chain DAG stores its scratch states and resolved values directly within the tail of the pre-allocated `ra_watch[RA_WATCH_MAX]` buffer (1,024 words):
```
[ direct watch addresses (N words) ] ... [ node descriptors ] ... [ resolved node values ]
```
If `watch_count + (node_count * 4) > RA_WATCH_MAX`, chain evaluation is safely disabled for that session, preserving direct telemetry without overflowing memory.

### 3.3 Snapshot Wire Protocol
```
+--------------------------------------------------------------+
| ra_snap Header (magic, seq, frame, dma_skip, game_id, ...)   |
+--------------------------------------------------------------+
| Direct Watch Values (little-endian byte stream)              |
+--------------------------------------------------------------+
| Pointer Chain Pairs (8 bytes per node: 4B addr + 4B value)   |
+--------------------------------------------------------------+
| Trailer (seq_end verification word)                          |
+--------------------------------------------------------------+
```
By sending both the resolved address and the final value, the companion PC tool (`xerabora`) can evaluate conditions instantaneously without requiring a second round-trip read.

---

## 4. Phased Implementation Roadmap

### Phase 1: Range Clamping Baseline (Completed in Tier 1)
- Implemented `RA_RAM_LOW` and `RA_RAM_HIGH` guards in `ee_core/src/ra.c` to protect flat memory reads from loading-screen crashes.

### Phase 2: Companion Protocol Negotiation
- Update `modules/network/common/ra_snap.h` with `RA_SNAP_MAX_BYTES` accounting for node pairs.
- Implement capability handshake in `xerabora` client to detect whether the connected console supports chain nodes.

### Phase 3: In-Game Evaluator & Validation
- Port the bounded loop in `ee_core/src/ra.c` that evaluates `ra_node` lists.
- Test against *X-Men Origins* and *Burnout 3: Takedown* on real hardware across USB, SMB, and internal HDD.
