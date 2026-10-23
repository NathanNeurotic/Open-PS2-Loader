#!/usr/bin/env python3
"""Run the production Language page through navigation, child edits and allocation failure."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
gui = (ROOT / "src/gui.c").read_text(encoding="utf-8")
dialogs = (ROOT / "src/dialogs.c").read_text(encoding="utf-8")
dia_h = (ROOT / "include/dia.h").read_text(encoding="utf-8")
dialogs_h = (ROOT / "include/dialogs.h").read_text(encoding="utf-8")


def function(signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", gui, re.M)
    assert match, signature
    return gui[match.start():gui.index("\n}", match.end()) + 2]


def array(name):
    return re.search(r"^struct UIItem " + name + r"\[\] = \{.*?\};", dialogs, re.M | re.S).group()


language = array("diaLanguageConfig")
assert len(re.findall(r"\{UI_ENUM, UICFG_LANG,", dialogs)) == 1
assert "UICFG_LANG" in language and "LAUNCH_OSD_DEFAULTS_BUTTON" in language
for old in ("diaConfig", "diaUIConfig", "diaLaunchConfig"):
    assert "UICFG_LANG" not in array(old), old
    assert "LAUNCH_OSD_DEFAULTS_BUTTON" not in array(old), old
index = function("static int guiSettingsShowIndex(")
assert "_l(_STR_LANGUAGE)" in index
shell = function("static void guiShowSettingsFromPage(")
assert re.search(r"case SETTINGS_LANGUAGE:\s*result = guiSettingsShowLanguage\(\);", shell)
assert "guiGameShowOSDLanguageConfig" not in function("static int guiSettingsShowLaunch(")

types = (re.search(r"^typedef enum \{.*?\} UIItemType;", dia_h, re.M | re.S).group()
         + "\n" + re.search(r"^struct UIItem\s*\{.*?^\};", dia_h, re.M | re.S).group())
page_enum = re.search(r"^enum gui_settings_page \{.*?\};", gui, re.M | re.S).group()
defines = "\n".join(re.findall(r"^#define DIA_RESULT_\w+\s+[^\n]+", dia_h, re.M))
defines += "\n" + re.search(r"^enum UI_ITEMS \{.*?\};", dialogs_h, re.M | re.S).group()
# Dialog IDs and translated labels come from the same headers as the production array.
labels = sorted(set(re.findall(r"\b_STR_\w+", language)))
defines += "\n" + "\n".join(f"#define {label} {i}" for i, label in enumerate(labels))

program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
@TYPES@
@DEFINES@
@ENUM@
@DIALOG@
static struct UIItem *guiSettingsActiveDialog, *shellUI;
static int guiSettingsShellActive = 1, guiSettingsCurrentPage = SETTINGS_LANGUAGE;
static int guiSettingsSavePending, context, lockDepth, calls, applyCalls, menuCalls, osdCalls;
static int currentLanguage, selectedLanguage, osdLanguage, childFirst, finalResult;
static int composeFails, allocFail, allocCalls, outstanding;
static char guiSettingsPageIndicator[32];
static char english[] = "English", japanese[] = "Japanese";
static const char *liveNames[] = {english, japanese, NULL};
static const char **boundNames;
static int picker;

static void *checkedMalloc(size_t size)
{
    void *ptr;
    if (allocCalls++ == allocFail) return NULL;
    ptr = malloc(size);
    if (ptr) outstanding++;
    return ptr;
}
static void checkedFree(void *ptr) { if (ptr) outstanding--; free(ptr); }
#define malloc checkedMalloc
#define free checkedFree
@COPY@
#undef malloc
#undef free

static struct UIItem *guiSettingsCompose(const struct UIItem **parts, int count,
                                       const int *skip, int skips, int part, int headers)
{
    assert(count == 1 && parts[0] == diaLanguageConfig);
    (void)skip; (void)skips; (void)part; (void)headers;
    guiSettingsActiveDialog = composeFails ? NULL : diaLanguageConfig;
    return guiSettingsActiveDialog;
}
static void guiLock(void) { assert(lockDepth++ == 0); }
static void guiUnlock(void) { assert(--lockDepth == 0); }
static const char **lngGetGuiList(void) { assert(lockDepth == 1); return liveNames; }
static int lngGetGuiValue(void) { return currentLanguage; }
static void diaSetEnum(struct UIItem *ui, int id, const char **names)
{
    assert(ui == diaLanguageConfig && id == UICFG_LANG);
    assert(names != liveNames && names[0] != liveNames[0]);
    boundNames = names;
}
static void diaSetInt(struct UIItem *ui, int id, int value)
{ (void)ui; assert(id == UICFG_LANG); picker = value; }
static void diaGetInt(struct UIItem *ui, int id, int *value)
{ (void)ui; assert(id == UICFG_LANG); *value = picker; }
static void diaSetSettingsShell(struct UIItem *ui, const char *indicator)
{
    shellUI = ui;
    if (ui) assert(strcmp(indicator, "3/9") == 0);
}
static void diaSetSettingsContext(int enabled) { context = enabled; }
static int diaExecuteDialog(struct UIItem *ui, int id, short menu, int (*updater)(int))
{
    assert(ui == shellUI && context && !lockDepth);
    assert(id == -1 && menu && !updater);
    assert(strcmp(boundNames[0], "English") == 0 && strcmp(boundNames[1], "Japanese") == 0);
    if (calls++ == 0) {
        assert(picker == currentLanguage);
        picker = selectedLanguage;
        /* Simulate discovery rebuilding the strings while this dialog owns its snapshot. */
        english[0] = 'X'; japanese[0] = 'X';
        if (childFirst) return LAUNCH_OSD_DEFAULTS_BUTTON;
    } else {
        assert(childFirst && picker == selectedLanguage);
    }
    return finalResult;
}
static void guiGameShowOSDLanguageConfig(int global)
{
    assert(global == 1 && currentLanguage == 0);
    osdLanguage = 7;
    osdCalls++;
}
static void applyConfig(int theme, int language, int skipDeviceRefresh)
{
    assert(theme == -1 && skipDeviceRefresh == 1);
    currentLanguage = language;
    applyCalls++;
}
static void menuReinitMainMenu(void) { menuCalls++; }
@FUNCTIONS@

static void reset(void)
{
    assert(outstanding == 0 && lockDepth == 0);
    guiSettingsActiveDialog = shellUI = NULL;
    context = guiSettingsSavePending = calls = applyCalls = menuCalls = osdCalls = 0;
    currentLanguage = selectedLanguage = 0;
    osdLanguage = 2;
    childFirst = composeFails = allocCalls = 0;
    allocFail = -1;
    english[0] = 'E'; japanese[0] = 'J';
}
static void expectExit(int result, int change, int child)
{
    int got;
    reset();
    finalResult = result;
    selectedLanguage = change;
    childFirst = child;
    got = guiSettingsShowLanguage();
    assert(got == (result == DIA_RESULT_PREV || result == DIA_RESULT_NEXT ? result : DIA_RESULT_INDEX));
    assert(currentLanguage == (result == UIID_BTN_CANCEL || result == -1 ? 0 : change));
    assert(applyCalls == (currentLanguage != 0) && menuCalls == applyCalls);
    assert(osdLanguage == (child ? 7 : 2) && osdCalls == child);
    assert(!guiSettingsActiveDialog && !shellUI && !context && !outstanding);
    assert(guiSettingsSavePending == (child || result != UIID_BTN_CANCEL));
}
int main(void)
{
    int i, result[] = {UIID_BTN_OK, DIA_RESULT_INDEX, DIA_RESULT_PREV, DIA_RESULT_NEXT, UIID_BTN_CANCEL, -1};
    assert(SETTINGS_PAGE_COUNT == 9);
    for (i = 0; i < (int)(sizeof(result) / sizeof(result[0])); i++) {
        expectExit(result[i], 0, 0);
        expectExit(result[i], 1, 0);
        expectExit(result[i], 1, 1);
    }
    for (i = 0; i < 3; i++) {
        reset(); allocFail = i;
        assert(guiSettingsShowLanguage() == DIA_RESULT_INDEX);
        assert(!calls && !applyCalls && !outstanding && !lockDepth);
        assert(!guiSettingsActiveDialog && !shellUI && !context && !guiSettingsSavePending);
    }
    reset(); composeFails = 1;
    assert(guiSettingsShowLanguage() == DIA_RESULT_INDEX && !allocCalls && !calls);
    puts("Language page: navigation keeps edits, OSD stays independent, snapshots survive discovery, allocation failures clean up");
    return 0;
}
'''
functions = "\n".join(function(sig) for sig in (
    "static int guiSettingsIsPeerResult(", "static int guiSettingsIsShellResult(",
    "static int guiSettingsPageResult(", "static void guiSettingsBeginDialog(",
    "static void guiSettingsEndDialog(", "static int guiSettingsShowLanguage("))
copies = "\n".join(function(sig) for sig in (
    "static const char **guiCopyNameList(", "static void guiFreeNameList("))
for marker, value in (("TYPES", types), ("DEFINES", defines), ("ENUM", page_enum),
                      ("DIALOG", language), ("COPY", copies), ("FUNCTIONS", functions)):
    program = program.replace("@" + marker + "@", value)

with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / "language_page.c"
    binary = Path(tmp) / ("language_page.exe" if os.name == "nt" else "language_page")
    source.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    "-Wno-missing-field-initializers", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Language picker and OSD Defaults have one Settings entry point")
