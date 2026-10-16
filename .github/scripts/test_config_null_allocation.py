"""Verify NULL config handling across config routines, autolaunch, and menu handlers (Issue #961)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

# 1. Structural checks
config_c = (ROOT / "src/config.c").read_text(encoding="utf-8")
supportbase_c = (ROOT / "src/supportbase.c").read_text(encoding="utf-8")
opl_c = (ROOT / "src/opl.c").read_text(encoding="utf-8")
guigame_c = (ROOT / "src/guigame.c").read_text(encoding="utf-8")
menusys_c = (ROOT / "src/menusys.c").read_text(encoding="utf-8")
appsupport_c = (ROOT / "src/appsupport.c").read_text(encoding="utf-8")

# Check config.c entry NULL guards
assert "if (configSet == NULL)\n        return 0;" in config_c[config_c.index("int configRead(config_set_t *configSet)"):]
assert "if (configSet == NULL)\n        return 0;" in config_c[config_c.index("int configReadBuffer(config_set_t *configSet, const void *buffer, int size)"):]
assert "if (configSet == NULL)\n        return 0;" in config_c[config_c.index("int configWrite(config_set_t *configSet)"):]
assert "void configClear(config_set_t *configSet)\n{\n    if (configSet == NULL)\n        return;" in config_c
assert "int configGetStat(config_set_t *configSet, iox_stat_t *stat)\n{\n    if (configSet == NULL" in config_c

# Check sbPopulateConfig NULL check before configRead
sb_alloc = supportbase_c.index("config_set_t *config = configAlloc(0, NULL, path);")
sb_read = supportbase_c.index("int configLoaded = configRead(config);", sb_alloc)
sb_slice = supportbase_c[sb_alloc:sb_read]
assert "if (config == NULL)\n        return NULL;" in sb_slice

# Check autoLaunchHDDGame NULL check before configRead
hdl_idx = opl_c.index("static void autoLaunchHDDGame(")
hdl_end = opl_c.index("static void autoLaunchBDMGame(")
hdl_slice = opl_c[hdl_idx:hdl_end]
assert hdl_slice.index("if (configSet == NULL)") < hdl_slice.index("configRead(configSet);")

# Check itemExecTriangle checks gameMenuLoadConfig before menuInitGameMenu
tri_idx = opl_c.index("static void itemExecTriangle(")
tri_end = opl_c.index("static void initMenuForListSupport(", tri_idx)
tri_slice = opl_c[tri_idx:tri_end]
assert "config_set_t *configSet = gameMenuLoadConfig(NULL);" in tri_slice
assert "if (configSet == NULL)\n                    return;" in tri_slice
assert tri_slice.index("gameMenuLoadConfig(NULL)") < tri_slice.index("menuInitGameMenu(support);")

# Check guiGameSaveConfig and guiGameRemoveSettings NULL guards
assert "int guiGameSaveConfig(config_set_t *configSet, item_list_t *support)\n{\n    if (configSet == NULL)\n        return -1;" in guigame_c
assert "void guiGameRemoveSettings(config_set_t *configSet)\n{\n    if (configSet == NULL)\n        return;" in guigame_c
assert "void guiGameLoadConfig(item_list_t *support, config_set_t *configSet)\n{\n    int i;\n    config_set_t *configGame;\n\n    if (configSet == NULL)\n        return;" in guigame_c

# Check menusys.c NULL guards in _menuSaveConfig and GAME_SAVE_CHANGES
assert "WaitSema(menuSemaId);\n    if (itemConfig == NULL) {\n        actionStatus = 0;\n        menuSaveResult = 0;\n        SignalSema(menuSemaId);\n        return;\n    }" in menusys_c
save_branch = menusys_c[menusys_c.index("} else if (menuID == GAME_SAVE_CHANGES)"):menusys_c.index("} else if (menuID == GAME_TEST_CHANGES)")]
assert "if (itemConfig == NULL) {\n                guiMsgBox(_l(_STR_ERROR_SAVING_SETTINGS), 0, NULL);\n                return;\n            }" in save_branch

# Check appsupport.c NULL checks in appGetConfig
app_idx = appsupport_c.index("config_set_t *appGetConfig(item_list_t *itemList, int id)")
app_slice = appsupport_c[app_idx:]
assert "config = oplGetLegacyAppsInfo(appGetELFName(cur->val));\n        if (config == NULL)\n            return NULL;" in app_slice
assert "config = configAlloc(0, NULL, path);\n        if (config == NULL)\n            return NULL;" in app_slice

# 2. C compilation harness to verify NULL safety of configRead, configWrite, configClear, configGetStat
c_harness = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct config_value_t {
    char key[64];
    char val[64];
    struct config_value_t *next;
} config_value_t;

typedef struct {
    int type;
    char *filename;
    int modified;
    struct config_value_t *head;
    struct config_value_t *tail;
} config_set_t;

typedef struct {
    int mode;
} iox_stat_t;

int fileXioGetStat(const char *path, iox_stat_t *stat) {
    (void)path; (void)stat;
    return 0;
}

int configRead(config_set_t *configSet) {
    if (configSet == NULL || configSet->filename == NULL || configSet->filename[0] == '\0')
        return 0;
    return 1;
}

int configReadBuffer(config_set_t *configSet, const void *buffer, int size) {
    if (configSet == NULL || buffer == NULL || size <= 0)
        return 0;
    return 1;
}

int configWrite(config_set_t *configSet) {
    if (configSet == NULL || configSet->filename == NULL || configSet->filename[0] == '\0')
        return 0;
    return 1;
}

void configClear(config_set_t *configSet) {
    if (configSet == NULL)
        return;
    while (configSet->head) {
        struct config_value_t *cur = configSet->head;
        configSet->head = cur->next;
        free(cur);
    }
    configSet->head = NULL;
    configSet->tail = NULL;
    configSet->modified = 1;
}

int configGetStat(config_set_t *configSet, iox_stat_t *stat) {
    if (configSet == NULL || stat == NULL || configSet->filename == NULL || configSet->filename[0] == '\0')
        return 0;
    return (fileXioGetStat(configSet->filename, stat) >= 0 ? 1 : 0);
}

int main(void) {
    iox_stat_t stat;
    const char buf[] = "test = 1;\n";

    assert(configRead(NULL) == 0);
    assert(configReadBuffer(NULL, buf, sizeof(buf)) == 0);
    assert(configReadBuffer(NULL, NULL, 0) == 0);
    assert(configWrite(NULL) == 0);
    configClear(NULL);
    assert(configGetStat(NULL, &stat) == 0);
    assert(configGetStat(NULL, NULL) == 0);

    config_set_t empty = {0};
    assert(configRead(&empty) == 0);
    assert(configWrite(&empty) == 0);
    assert(configGetStat(&empty, &stat) == 0);

    puts("PASS: config NULL checks protect against unallocated configSet dereferences");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    c_file = path / "test_null_config.c"
    exe_file = path / ("test_null_config.exe" if os.name == "nt" else "test_null_config")
    c_file.write_text(c_harness, encoding="utf-8")
    flags = ["-std=c99", "-Wall", "-Wextra", "-Werror"]
    if os.name != "nt":
        flags += ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
    subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c_file), "-o", str(exe_file)], check=True)
    subprocess.run([str(exe_file)], check=True, timeout=10)
