"""Settings > Interface > List Title and Description (from RIPPS2 build 126).

A theme's AttributeText that shows the game CFG's Title or Description is hidden on the list pages when
the setting is Off, or when it is Theme (the default) and the theme sets list_cfg_text=0. On shows them
whatever the theme says. The info page always shows them, and every other attribute is untouched.

Compiles the production renderer (drawAttributeText with its List Title helpers, initAttributeText and
thmElemIsInfo) against fake theme families and runs every setting x theme key x family x attribute. The
element's family decides list page or info page, not its block name: a view's blocks are named like
grid.main0. Then it runs the theme's list_cfg_text parse and checks the setting's wiring: config key,
default, clamp, settings row and strings.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
CPP = (root / "src/gfx/themeelems.cpp").exists()


def read(c_path, cpp_path):
    return (root / (cpp_path if CPP else c_path)).read_text(encoding="utf-8")


def definition(source, name):
    """The body of function `name`, skipping any forward declaration."""
    match = re.search(r"^(?:static )?[\w ]+\**\b" + name + r"\([^;{]*\)\s*\{", source, re.M)
    assert match, name
    depth = 0
    for index in range(source.index("{", match.start()), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[match.start():index + 1]
    raise AssertionError(name)


elems = read("src/themes.c", "src/gfx/themeelems.cpp")
code = "\n\n".join(definition(elems, name) for name in (
    "thmElemIsInfo", "thmListCfgTextShown", "thmCfgTextHidden", "drawAttributeText", "initAttributeText"))
themes = read("src/themes.c", "src/gfx/themes.cpp")
key_line = re.search(r"newT->hideListCfgText = [^;]+;", themes)
assert key_line, "the theme's list_cfg_text key is read"

if CPP:
    config = "typedef struct config_set { int id, count; kv_t kv[4]; int uid() const { return id; } } config_set_t;"
    setuid = "c->id = uid;"
else:
    config = "typedef struct config_set { int uid, count; kv_t kv[4]; } config_set_t;"
    setuid = "c->uid = uid;"

program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CONFIG_ITEM_NAME "#Name"
#define CONFIG_ITEM_SIZE "#Size"
#define SIZING_NONE 0
#define SIZING_WRAP 1
#define DISPLAY_NEVER 0
#define DISPLAY_ALWAYS 1
#define ELEM_TYPE_ATTRIBUTE_TEXT 7
#define _STR_SIZE 0
#define LOG(...) ((void)0)
enum { LIST_CFG_TEXT_THEME = 0, LIST_CFG_TEXT_ON, LIST_CFG_TEXT_OFF };
static int gListCfgText;
struct menu_list { int unused; };
struct submenu_list { int unused; };
typedef struct { const char *key, *value; } kv_t;
@CONFIG@
typedef struct {
    int currentConfigId, sizingMode, displayMode;
    char *value, *currentValue, *wrappedValue, *alias;
    unsigned char cfgText;
} mutable_text_t;
typedef struct theme_elems { int unused; } theme_elems_t;
typedef struct theme_element {
    void *extended;
    int font, width;
    struct theme_elems *family;
    void (*drawElem)(struct menu_list *, struct submenu_list *, config_set_t *, struct theme_element *);
    void (*endElem)(struct theme_element *);
} theme_element_t;
typedef struct theme {
    theme_elems_t mainElems, appsMainElems, favsMainElems, vcdMainElems, favsVcdMainElems, favsAppsMainElems;
    theme_elems_t infoElems, appsInfoElems, favsInfoElems, vcdInfoElems, favsVcdInfoElems, favsAppsInfoElems;
    int hideListCfgText;
} theme_t;
static theme_t gThemeStore;
static theme_t *gTheme = &gThemeStore;
static char drawn[300];
static const char *_l(int id) { (void)id; return "Size"; }
static int configGetStr(config_set_t *c, const char *key, const char **out)
{
    int i;
    for (i = 0; i < c->count; i++)
        if (!strcmp(c->kv[i].key, key)) {
            *out = c->kv[i].value;
            return 1;
        }
    return 0;
}
static void fntFitString(int font, char *value, int width) { (void)font; (void)value; (void)width; }
static void thmDrawElemText(theme_element_t *elem, int mode, const char *s, int flag)
{
    (void)elem; (void)mode; (void)flag;
    snprintf(drawn, sizeof(drawn), "%s", s);
}
static mutable_text_t *initMutableText(const char *themePath, config_set_t *themeConfig, theme_t *theme, const char *name, int type,
                                       struct theme_element *elem, const char *value, const char *alias, int displayMode, int sizingMode)
{
    mutable_text_t *t = (mutable_text_t *)calloc(1, sizeof(mutable_text_t));
    (void)themePath; (void)themeConfig; (void)theme; (void)name; (void)type; (void)elem; (void)alias;
    t->value = strdup(value);
    t->alias = (char *)"";
    t->displayMode = displayMode;
    t->sizingMode = sizingMode;
    t->cfgText = 7; /* initAttributeText must set it either way */
    return t;
}
static void endMutableText(struct theme_element *elem) { (void)elem; }

@CODE@

static const char *keyValue; /* the theme's list_cfg_text, NULL when it has none */
static int thmViewGetInt(config_set_t *themeConfig, const char *prefix, const char *key, int *value)
{
    (void)themeConfig; (void)prefix;
    if (strcmp(key, "list_cfg_text") || keyValue == NULL)
        return 0;
    *value = atoi(keyValue);
    return 1;
}
static int themeHides(const char *value)
{
    theme_t t;
    theme_t *newT = &t;
    config_set_t *themeConfig = NULL;
    const char *viewPrefix = "";
    int intValue = 0;
    memset(&t, 0, sizeof(t));
    keyValue = value;
    @KEYLINE@
    return newT->hideListCfgText;
}

static void setGame(config_set_t *c, int uid, const char *tag)
{
    static char title[64], desc[64];
    snprintf(title, sizeof(title), "%s Title", tag);
    snprintf(desc, sizeof(desc), "%s Description", tag);
    @SETUID@
    c->count = 4;
    c->kv[0].key = "Title"; c->kv[0].value = title;
    c->kv[1].key = "Description"; c->kv[1].value = desc;
    c->kv[2].key = "Genre"; c->kv[2].value = "Game Genre";
    c->kv[3].key = "#Name"; c->kv[3].value = "Library Name";
}

static void newElem(theme_element_t *elem, const char *attribute, theme_elems_t *family)
{
    config_set_t themeConfig;
    memset(&themeConfig, 0, sizeof(themeConfig));
    themeConfig.count = 1;
    themeConfig.kv[0].key = "elem0_attribute";
    themeConfig.kv[0].value = attribute;
    memset(elem, 0, sizeof(*elem));
    initAttributeText(NULL, &themeConfig, gTheme, elem, "elem0");
    assert(elem->drawElem != NULL && elem->extended != NULL);
    elem->family = family;
}

int main(void)
{
    theme_elems_t *families[] = {&gTheme->mainElems, &gTheme->appsMainElems, &gTheme->favsMainElems, &gTheme->vcdMainElems,
                                 &gTheme->favsVcdMainElems, &gTheme->favsAppsMainElems,
                                 &gTheme->infoElems, &gTheme->appsInfoElems, &gTheme->favsInfoElems, &gTheme->vcdInfoElems,
                                 &gTheme->favsVcdInfoElems, &gTheme->favsAppsInfoElems};
    const char *attributes[] = {"Title", "Description", "Genre", "#Name"};
    const char *values[] = {"Game Title", "Game Description", "Game Genre", "Library Name"};
    struct submenu_list item = {0};
    config_set_t game;
    theme_element_t elem;
    int f, a, mode, hides, uid = 1, checked = 0;

    for (f = 0; f < 12; f++) {
        for (a = 0; a < 4; a++) {
            newElem(&elem, attributes[a], families[f]);
            assert(((mutable_text_t *)elem.extended)->cfgText == (a < 2 ? 1 : 0));
            for (mode = LIST_CFG_TEXT_THEME; mode <= LIST_CFG_TEXT_OFF; mode++) {
                for (hides = 0; hides < 2; hides++) {
                    int info = f >= 6;
                    int shown = a >= 2 || info || mode == LIST_CFG_TEXT_ON || (mode == LIST_CFG_TEXT_THEME && !hides);
                    gListCfgText = mode;
                    gTheme->hideListCfgText = hides;
                    setGame(&game, uid++, "Game");
                    drawn[0] = 0;
                    elem.drawElem(NULL, &item, &game, &elem);
                    if (shown && strcmp(drawn, values[a])) {
                        printf("FAIL family %d %s, setting %d, theme hides %d: drew \"%s\", want \"%s\"\n", f, attributes[a], mode, hides, drawn, values[a]);
                        return 1;
                    }
                    if (!shown && drawn[0]) {
                        printf("FAIL family %d %s, setting %d, theme hides %d: drew \"%s\", want nothing\n", f, attributes[a], mode, hides, drawn);
                        return 1;
                    }
                    checked++;
                }
            }
        }
    }

    /* A frame skipped while hidden must not leave the last game's text behind for the next one shown. */
    newElem(&elem, "Title", &gTheme->vcdMainElems);
    gTheme->hideListCfgText = 0;
    gListCfgText = LIST_CFG_TEXT_ON;
    setGame(&game, 900, "First");
    elem.drawElem(NULL, &item, &game, &elem);
    assert(!strcmp(drawn, "First Title"));
    gListCfgText = LIST_CFG_TEXT_OFF;
    setGame(&game, 901, "Second");
    drawn[0] = 0;
    elem.drawElem(NULL, &item, &game, &elem);
    assert(!drawn[0]);
    gListCfgText = LIST_CFG_TEXT_THEME;
    elem.drawElem(NULL, &item, &game, &elem);
    assert(!strcmp(drawn, "Second Title"));

    /* The theme key: only list_cfg_text=0 hides them; absent or any other value shows them as before. */
    assert(themeHides(NULL) == 0);
    assert(themeHides("0") == 1);
    assert(themeHides("1") == 0);
    assert(themeHides("2") == 0);

    printf("PASS: List Title and Description: %d draws over every family, attribute, setting and theme key\n", checked);
    return 0;
}
'''.replace("@CONFIG@", config).replace("@SETUID@", setuid).replace("@CODE@", code).replace("@KEYLINE@", key_line.group(0))

# -Wno-unused-function: a helper the renderer stops calling must fail by what it draws, not by a warning.
with tempfile.TemporaryDirectory(prefix="listcfg-") as tmp:
    src, exe = Path(tmp) / ("t.cpp" if CPP else "t.c"), Path(tmp) / "t"
    src.write_text(program, encoding="utf-8")
    if CPP:
        cmd = ["c++", "-std=gnu++17", "-Wall", "-Werror", "-Wno-unused-function", "-x", "c++", str(src), "-o", str(exe)]
    else:
        cmd = ["cc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function", "-x", "c", str(src), "-o", str(exe)]
    subprocess.run(cmd, check=True)
    subprocess.run([str(exe)], check=True)

# Wiring ------------------------------------------------------------------------------------------
opl_h = (root / "include/opl.h").read_text(encoding="utf-8")
assert re.search(r"enum \{ LIST_CFG_TEXT_THEME = 0,\s*LIST_CFG_TEXT_ON,\s*LIST_CFG_TEXT_OFF \};", opl_h), "Theme, On, Off"
assert '"list_cfg_text"' in (root / "include/config.h").read_text(encoding="utf-8")
if CPP:  # one settings table loads and saves every key
    table = (root / "src/core/settings.cpp").read_text(encoding="utf-8")
    assert "intSetting(CONFIG_OPL_LIST_CFG_TEXT, &gListCfgText, LIST_CFG_TEXT_THEME)" in table, "saved, default Theme"
    load = (root / "src/app/settingsio.cpp").read_text(encoding="utf-8")
else:
    load = (root / "src/opl.c").read_text(encoding="utf-8")
    assert "configGetInt(configOPL, CONFIG_OPL_LIST_CFG_TEXT, &gListCfgText)" in load, "loaded"
    assert "configSetInt(configOPL, CONFIG_OPL_LIST_CFG_TEXT, gListCfgText)" in load, "saved"
    assert "gListCfgText = LIST_CFG_TEXT_THEME;" in definition(load, "setDefaults"), "default Theme"
assert re.search(r"if \(gListCfgText < LIST_CFG_TEXT_THEME \|\| gListCfgText > LIST_CFG_TEXT_OFF\)\s*gListCfgText = LIST_CFG_TEXT_THEME;", load), \
    "a saved value out of range reads as Theme"

dialogs = read("src/dialogs.c", "src/ui/dialogs.cpp")
assert re.search(r"\{UI_LABEL, 0, 1, 1, -1, -40, 0, \{\.label = \{NULL, _STR_LIST_CFG_TEXT\}\}\},\s*\{UI_SPACER\},\s*"
                 r"\{UI_ENUM, UICFG_LIST_CFG_TEXT, 1, 1, _STR_HINT_LIST_CFG_TEXT,", dialogs), "Settings > Interface row"
gui = read("src/gui.c", "src/ui/guisettings.cpp")
assert "{_l(_STR_THEME), _l(_STR_ON), _l(_STR_OFF), NULL}" in gui, "the choices in LIST_CFG_TEXT_* order"
assert re.search(r"diaSetInt\(\w+, UICFG_LIST_CFG_TEXT, gListCfgText\)", gui)
assert re.search(r"diaGetInt\(\w+, UICFG_LIST_CFG_TEXT, &gListCfgText\)", gui)

base = (root / ("lng/tmpl/_base.yml" if CPP else "lng_tmpl/_base.yml")).read_text(encoding="utf-8")
for label in ("LIST_CFG_TEXT", "HINT_LIST_CFG_TEXT"):
    assert "label: " + label + "\n" in base, label
assert base.index("label: LIST_CFG_TEXT\n") > base.index("label: PS1_DUPLICATES_BOTH\n"), "appended: every existing string keeps its ID"
print("PASS: List Title and Description is saved, defaults to Theme, clamps a bad value and has its Interface row")
