# Problem Proposition and Proposed Fixes

This document outlines two issues identified in the Open PS2 Loader codebase and provides instructions for another agent to implement the code changes.

## 1. APA HDD vs. BDM exFAT Conflict

### Problem Description
When BDM (for USB exFAT devices) is active and the APA HDD device is set to Auto, the internal HDD spins up and APA HDD game scanning and browsing completely break.
The root cause is un-arbitrated hardware access on the DEV9/ATA interface. The BDM FATFS module auto-mounts the low-level ATA helper driver (`xhdd.irx`) because it registers itself as a block device. BDM sends a barrage of sector read commands during its mount attempts which collide with the legitimate APA drivers' access to the drive.

### Proposed Code Fix
1. Modify `modules/hdd/xhdd/xhdd.c`: Update the entry point `_start` to parse a `-nobdm` command-line argument. If the flag is passed, register the device as a character device instead of a block device. This allows OPL to use it for LBA48/UDMA settings but stops BDM from scanning it.
   ```c
   int noBdm = 0;
   for (i = 1; i < argc; i++) {
       if (!strcmp(argv[i], "-nobdm"))
           noBdm = 1;
       if (!strcmp(argv[i], "-hdpro"))
           isHDPro = 1;
   }

   if (noBdm)
       xhddDevice.type = IOP_DT_CHAR; // Prevents bdmfs_fatfs from mounting it
   ```

2. Modify `src/hddsupport.c`: Update `hddLoadModules()` where it loads `xhdd_irx`. If BDM HDD is disabled (`gEnableBdmHDD == 0`), pass the `-nobdm` argument. Change `sysLoadModuleBuffer(&xhdd_irx, size_xhdd_irx, 0, NULL);` to `sysLoadModuleBuffer(&xhdd_irx, size_xhdd_irx, 7, "-nobdm");` or append it appropriately.

## 2. Favorites Info Page Missing Fields (Issue #54)

### Problem Description
When browsing the Favorites tab (`FAV_MODE`) and opening the Info page for an item, several text fields are missing or not rendering. All other display-related elements on the Info page work fine across other devices.

### Root Cause Analysis and Proposed Code Fix
The issue relates to how the theme elements are parsed and how `itemConfig` is loaded for the `FAV_MODE` info page.
There are two areas to check and address:

1. **Theme Elements Parsing for `favsInfo`**:
In `src/themes.c`, in the function `thmAddGUIElems` (around line 2572), when parsing elements for the `favsInfo` family, the logic correctly tries to fallback to `info%d` if `favsInfo%d` is missing.
```c
    // Favourites info family: favsInfo<j> override, else info<j> (identical to appsInfo).
    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "favsInfo%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->favsInfoElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "info%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->favsInfoElems, NULL, path);
        }
    }
```
This looks structurally correct, but if custom themes have issues falling back, ensure the elements are properly populated.

2. **`itemConfig` loading for Info Page (`_menuResolveInfoSize` and `favGetConfig`)**:
In `src/menusys.c` line 257, `_menuResolveInfoSize()` is called when the Info page opens to stat the file for its `#Size`.
```c
    if (selected_item != NULL && selected_item->item != NULL && selected_item->item->current != NULL && itemConfigId >= 0 && itemConfigId == selected_item->item->current->item.id) {
```
Ensure that for items on the Favorites tab (`FAV_MODE`), `itemConfigId == selected_item->item->current->item.id` correctly matches, because favorites have their own IDs that proxy to the original device item IDs. If the ID check fails, `_menuResolveInfoSize` bails out, and the size field is never resolved. Furthermore, `menuCanRequestItemConfig` and `_menuRequestConfig` might not be reliably loading the full `itemConfig` properties specifically for the favorites info page render pass.

Fixing `_menuResolveInfoSize` to properly resolve the size and config for the current item in `FAV_MODE`, and ensuring `menuRenderInfo` accesses this correctly via `menuGetInfoElems` and `favGetConfig`, will resolve the missing fields on the Favorites Info page.
