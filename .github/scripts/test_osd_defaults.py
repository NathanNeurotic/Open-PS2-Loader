#!/usr/bin/env python3
"""Exercise the real OSD editor's in-memory defaults and per-game scope lifetime."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/guigame.c").read_text(encoding="utf-8")
dialogs_h = (ROOT / "include/dialogs.h").read_text(encoding="utf-8")
config_h = (ROOT / "include/config.h").read_text(encoding="utf-8")
game_h = (ROOT / "include/guigame.h").read_text(encoding="utf-8")


def function(signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", source, re.M)
    assert match, signature
    return source[match.start():source.index("\n}", match.end()) + 2]


definitions = re.search(r"^enum UI_ITEMS \{.*?\};", dialogs_h, re.M | re.S).group()
definitions += "\n" + "\n".join(re.findall(r"^#define CONFIG_ITEM_OSD_SETTINGS_\w+\s+[^\n]+", config_h, re.M))
definitions += "\n" + "\n".join(re.findall(r"^#define SETTINGS_(?:GLOBAL|PERGAME)\s+[^\n]+", game_h, re.M))
functions = "\n".join(function(sig) for sig in (
    "static void guiGameLoadOSDLanguageConfig(", "void guiGameSaveOSDLanguageGlobalConfig(",
    "static int guiGameOSDLanguageUpdater(", "void guiGameShowOSDLanguageConfig("))
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
@DEFINITIONS@
#define CONFIG_GAME 1
#define _l(id) "label"
struct UIItem { int unused; };
static struct UIItem diaOSDConfig[1];
typedef struct { int value[5]; } config_set_t;
static config_set_t globalConfig, gameConfig;
static const char *keys[] = {CONFIG_ITEM_OSD_SETTINGS_ENABLE, CONFIG_ITEM_OSD_SETTINGS_LANGID,
    CONFIG_ITEM_OSD_SETTINGS_TV_ASP, CONFIG_ITEM_OSD_SETTINGS_VMODE, CONFIG_ITEM_OSD_SETTINGS_SOURCE};
static int forceGlobalOSDLanguage, gOSDLanguageSource, gOSDLanguageEnable, gOSDLanguageValue;
static int gOSDTVAspectRatio, gOSDVideOutput, rows[1024], nextLanguage, exitResult, globalWrites;
static int keyIndex(const char *key) {
    for (int i = 0; i < 5; i++) if (!strcmp(keys[i], key)) return i;
    assert(0); return 0;
}
static int configGetInt(config_set_t *config, const char *key, int *value) {
    assert(config); *value = config->value[keyIndex(key)]; return 1;
}
static int configSetInt(config_set_t *config, const char *key, int value) {
    assert(config); config->value[keyIndex(key)] = value;
    if (config == &globalConfig) globalWrites++;
    return 1;
}
static void configRemoveKey(config_set_t *config, const char *key) { configSetInt(config, key, 0); }
static config_set_t *configGetByType(int type) { assert(type == CONFIG_GAME); return &globalConfig; }
static config_set_t *gameMenuLoadConfig(struct UIItem *ui) { (void)ui; return &gameConfig; }
static void diaSetInt(struct UIItem *ui, int id, int value) { (void)ui; assert(id < 1024); rows[id] = value; }
static void diaGetInt(struct UIItem *ui, int id, int *value) { (void)ui; assert(id < 1024); *value = rows[id]; }
static void diaSetEnabled(struct UIItem *ui, int id, int enabled) { (void)ui; (void)id; (void)enabled; }
static void diaSetEnum(struct UIItem *ui, int id, const char **names) { (void)ui; (void)id; (void)names; }
static int diaExecuteDialog(struct UIItem *ui, int id, short menu, int (*updater)(int)) {
    assert(ui == diaOSDConfig && id == -1 && menu);
    if (nextLanguage >= 0) {
        rows[OSD_LANGUAGE_ENABLE] = 1;
        rows[OSD_LANGUAGE_VALUE] = nextLanguage;
    } else {
        assert(rows[OSD_LANGUAGE_VALUE] == globalConfig.value[1]);
    }
    updater(nextLanguage >= 0);
    return exitResult;
}
@FUNCTIONS@
int main(void) {
    /* Global changes must be available to another editor/launch without a disk save. */
    globalConfig = (config_set_t){{1, 1, 2, 1, SETTINGS_GLOBAL}};
    nextLanguage = 7; exitResult = UIID_BTN_OK;
    guiGameShowOSDLanguageConfig(1);
    assert(globalConfig.value[1] == 7 && globalConfig.value[2] == 2 && globalConfig.value[3] == 1);
    assert(!forceGlobalOSDLanguage);
    nextLanguage = -1;
    guiGameShowOSDLanguageConfig(1);
    assert(gOSDLanguageValue == 7 && !forceGlobalOSDLanguage);
    /* Leaving a global editor must not disable the next game's override. */
    gameConfig = (config_set_t){{1, 3, 0, 0, SETTINGS_PERGAME}};
    guiGameLoadOSDLanguageConfig(&gameConfig, &globalConfig);
    assert(gOSDLanguageSource == SETTINGS_PERGAME && gOSDLanguageValue == 3);
    int writes = globalWrites;
    nextLanguage = 4;
    guiGameShowOSDLanguageConfig(0);
    assert(globalWrites == writes && globalConfig.value[1] == 7);
    /* Back retains the editor's live values, consistently with Settings navigation. */
    nextLanguage = 6; exitResult = UIID_BTN_CANCEL;
    guiGameShowOSDLanguageConfig(1);
    assert(globalConfig.value[1] == 6 && !forceGlobalOSDLanguage);
    puts("OSD defaults: reopening retains edits, global scope ends with the editor, per-game overrides stay independent");
}
'''.replace("@DEFINITIONS@", definitions).replace("@FUNCTIONS@", functions)
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "osd_defaults.c"
    binary = Path(tmp) / ("osd_defaults.exe" if os.name == "nt" else "osd_defaults")
    c.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", str(c), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
