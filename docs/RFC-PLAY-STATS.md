# RFC: Persistent Gameplay Time and Statistics Tracking

## Status: Proposed / Banked for Staged Implementation
**Branch Reference:** `oplattice/main` & community requests  
**Target Subsystems:** `src/system.c`, `src/config.c`, `src/themes.c`, `ee_core/src/coreconfig.c`

---

## 1. Executive Summary
Modern game launchers and dashboards report gameplay statistics, including total accumulated play time, number of times launched, and last played timestamp. Users frequently request this capability in Open PS2 Loader.

While conceptually straightforward, tracking time on a PlayStation 2 presents unique challenges:
1. The Real-Time Clock (RTC) on many legacy consoles may be unconfigured or have a depleted battery.
2. In-game play continues after OPL transfers control to the game ELF; OPL does not remain resident in memory during retail gameplay.
3. Flash memory (Memory Card) write endurance must be protected against frequent unnecessary writes.

This RFC outlines a reliable, flash-safe architecture for recording and displaying game play statistics in OPL.

---

## 2. Technical Architecture

### 2.1 Session Tracking Flow
```
[User Selects Game]
       │
       ▼
1. OPL records Start Timestamp (RTC) or Tick Count in persistent scratch / conf_last.cfg.
2. Increments launch_count in CFG/<game_id>.cfg.
       │
       ▼
[Game Executes via ee_core]
       │
       ▼
[User Triggers IGR (In-Game Reset)]
       │
       ▼
3. OPL re-initializes from ELF.
4. Reads previous launch record from conf_last.cfg.
5. Calculates elapsed duration: (IGR_Return_Time - Start_Time).
6. Adds elapsed duration to total_play_time_seconds.
7. Commits updated stats to CFG/<game_id>.cfg.
```

### 2.2 Handling Hard Power-Offs (Non-IGR Exits)
If the player turns off the console power switch instead of using the IGR button combo (`L1+R1+L2+R2+L3+R3`):
- OPL cannot run code at the moment of power-off.
- On next boot, OPL checks `conf_last.cfg` for an unclosed session marker.
- Since the exact duration cannot be verified, OPL can either:
  a. Discard the unclosed session, OR
  b. Add a configurable nominal session increment (e.g. average session duration) or mark the session as unconfirmed.
- This prevents bogus infinite timestamps if months pass between boots.

### 2.3 Theme Engine Integration
Expose play statistics to themes via new `AttributeText` attributes:
- `PlayTime`: Formatted as `"XXh YYm"` or `"XX hours"`.
- `PlayCount` / `LaunchCount`: Integer count of launches.
- `LastPlayed`: Formatted date string (`"YYYY-MM-DD"`).

```ini
# Example in conf_theme.cfg
info_playtime:
    type=AttributeText
    attribute=PlayTime
    x=40
    y=380
    font=1
    color=#E0E0E0
```

---

## 3. Implementation Plan

1. **Phase 1: Config Schema & IO Safe Persistence:** Implement `sysRecordGameLaunch()` and `sysFinalizeGameSession()` in `src/system.c`, saving atomically to `CFG/<game_id>.cfg`.
2. **Phase 2: RTC & Clock Robustness:** Validate RTC availability; fall back to elapsed monotonic timer if RTC is unavailable.
3. **Phase 3: Theme Integration:** Add attribute resolvers in `src/themes.c` for `PlayTime`, `LaunchCount`, and `LastPlayed`.
