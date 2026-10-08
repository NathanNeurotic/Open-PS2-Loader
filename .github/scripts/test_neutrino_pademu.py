"""Execute the production PADEMU warning and core-selection logic with host stubs."""
from pathlib import Path
import subprocess
import tempfile
import re

root = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (root / path).read_text(encoding="utf-8")
    # Keep offsets while hiding C comments and literals from the brace scanner.
    masked = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda match: " " * len(match.group()), source, flags=re.DOTALL)
    start = source.index(signature)
    brace = masked.index("{", start)
    depth = 1
    end = brace + 1
    while depth and end < len(source):
        depth += (masked[end] == "{") - (masked[end] == "}")
        end += 1
    if depth:
        raise ValueError(f"Unterminated function: {path}: {signature}")
    return source[start:end]


warning = function("src/system.c", "void sysNeutrinoWarnPadEmu(")
core = function("src/menusys.c", "static int gameMenuCoreIsNeutrino(")
for path in ("src/bdmsupport.c", "src/hddsupport.c", "src/mmcesupport.c", "src/udpfssupport.c"):
    source = (root / path).read_text(encoding="utf-8")
    args = source.index("if (sysNeutrinoArgsPreflight(")
    notice = source.index("sysNeutrinoWarnPadEmu(configSet);", args)
    assert args < notice < source.index("sysLaunchNeutrino(", notice), path

program = r'''
#include <assert.h>
#include <stddef.h>
#define CONFIG_GAME 1
#define CONFIG_ITEM_PADEMUSOURCE 1
#define CONFIG_ITEM_ENABLEPADEMU 2
#define CONFIG_ITEM_CORE_LOADER 3
#define _STR_NEUTRINO_PADEMU_WARN 1
#define LOG(...) ((void)0)
typedef struct { int source_present, source, enabled_present, enabled, core_present, core; } config_set_t;
static config_set_t global, game;
static void *gAutoLaunchGame, *gAutoLaunchBDMGame;
static int notices;
static config_set_t *configGetByType(int type) { (void)type; return &global; }
static int configGetInt(config_set_t *c, int key, int *value) {
    if (!c) return 0;
    if (key == CONFIG_ITEM_PADEMUSOURCE && c->source_present) { *value=c->source; return 1; }
    if (key == CONFIG_ITEM_ENABLEPADEMU && c->enabled_present) { *value=c->enabled; return 1; }
    if (key == CONFIG_ITEM_CORE_LOADER && c->core_present) { *value=c->core; return 1; }
    return 0;
}
static const char *_l(int id) { (void)id; return "warning"; }
static int guiMsgBox(const char *text, int confirm, void *unused) {
    (void)text; (void)confirm; (void)unused; notices++; return 1;
}
enum { ETH_MODE=1, HTTP_MODE, UDPFS_MODE, BDM_MODE, FAV_MODE, HDD_MODE, LIB_VIEW_PS1 };
typedef struct { int mode; } item_list_t;
typedef struct { struct { int id; } item; } row_t;
typedef struct { void *userdata; row_t *current; } menu_t;
typedef struct { menu_t *item; } selected_t;
static item_list_t support;
static row_t row;
static menu_t menu = { &support, &row };
static selected_t selected = { &menu }, *selected_item = &selected;
static config_set_t *itemConfig = &game;
static int gDefaultCoreLoader, view, favMode, udpbd;
static int menuSelectedRowView(item_list_t *s) { (void)s; return view; }
static int favGetItemSourceMode(int id) { (void)id; return favMode; }
static int bdmModeIsUDPBD(int mode) { return mode == BDM_MODE && udpbd; }
static int bdmSupportIsUDPBD(void *s) { return bdmModeIsUDPBD(((item_list_t *)s)->mode); }
@WARNING@
@CORE@
int main(void) {
    global.enabled_present=1; global.enabled=1;
    sysNeutrinoWarnPadEmu(&game); assert(notices == 1);
    game.source_present=1; game.source=1; game.enabled_present=1; game.enabled=0;
    sysNeutrinoWarnPadEmu(&game); assert(notices == 1);
    game.enabled=1; global.enabled=0;
    sysNeutrinoWarnPadEmu(&game); assert(notices == 2);
    game.enabled_present=0;
    sysNeutrinoWarnPadEmu(&game); assert(notices == 2);
    game.enabled_present=1; game.enabled=1;
    gAutoLaunchGame=&game; sysNeutrinoWarnPadEmu(&game); assert(notices == 2);
    gAutoLaunchGame=NULL; gAutoLaunchBDMGame=&game;
    sysNeutrinoWarnPadEmu(&game); assert(notices == 2); gAutoLaunchBDMGame=NULL;
    support.mode=FAV_MODE; menu.current=NULL; view=0; gDefaultCoreLoader=0; game.core_present=0;
    assert(!gameMenuCoreIsNeutrino()); menu.current=&row;
    for (int favourite=0; favourite<2; favourite++) {
        for (int mode=ETH_MODE; mode<=HDD_MODE; mode++) {
            if (mode == FAV_MODE) continue;
            support.mode=favourite ? FAV_MODE : mode; favMode=mode;
            for (int defaultCore=0; defaultCore<2; defaultCore++) {
                gDefaultCoreLoader=defaultCore;
                for (int choice=-1; choice<2; choice++) {
                    game.core_present=choice>=0; game.core=choice;
                    for (udpbd=0; udpbd<2; udpbd++) {
                        view=0;
                        int expected=choice<0 ? defaultCore : choice;
                        if (mode==ETH_MODE || mode==HTTP_MODE) expected=0;
                        if (mode==UDPFS_MODE || (mode==BDM_MODE && udpbd)) expected=1;
                        assert(gameMenuCoreIsNeutrino()==expected);
                        view=LIB_VIEW_PS1; assert(gameMenuCoreIsNeutrino()==0);
                    }
                }
            }
        }
    }
    return 0;
}
'''.replace("@WARNING@", warning).replace("@CORE@", core)

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.c").write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-DPADEMU",
                    str(path / "test.c"), "-o", str(path / "test.exe")], check=True)
    subprocess.run([str(path / "test.exe")], check=True)
    # PADEMU-disabled builds must keep the shared launch calls harmless.
    disabled = "#include <stddef.h>\ntypedef int config_set_t;\n" + warning + "\nint main(void) { sysNeutrinoWarnPadEmu(NULL); return 0; }\n"
    (path / "disabled.c").write_text(disabled, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                    str(path / "disabled.c"), "-o", str(path / "disabled.exe")], check=True)
    subprocess.run([str(path / "disabled.exe")], check=True)
print("Neutrino PADEMU: inheritance, autolaunch, forced sources and Favourites passed")
