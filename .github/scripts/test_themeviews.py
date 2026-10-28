"""Exercise multi-view theme resolution (src/themeviews.c, docs/MULTI-VIEW-THEMES-PLAN.md).

Which views a theme offers, which one loads, and which block each family slot resolves to in that view.
The real src/themeviews.c is compiled against a small config stub that composes "section:" + indented
keys into "<section>_<key>" and truncates keys at the real CONFIG_KEY_NAME_LEN, as src/config.c does.
Design: KrahJohlito.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CONFIG_H = (ROOT / 'include/config.h').read_text(encoding='utf-8')
HEADER = (ROOT / 'include/themeviews.h').read_text(encoding='utf-8')
SOURCE = (ROOT / 'src/themeviews.c').read_text(encoding='utf-8')
THEMES = (ROOT / 'src/themes.c').read_text(encoding='utf-8')

KEY_LEN = int(re.search(r'#define CONFIG_KEY_NAME_LEN\s+(\d+)', CONFIG_H).group(1))
# The longest per-family key behind the longest view prefix must fit, or view blocks silently lose keys.
assert len('coverflow.favsVcdMain12_reflection_offset') < KEY_LEN, KEY_LEN
assert '#define CONFIG_OPL_THEME_VIEW' in CONFIG_H

# The loader builds every slot family through the view resolver, and resets the parse prefix afterwards.
load = THEMES[THEMES.index('static int thmLoad(const char *themePath)'):]
load = load[:load.index('\n}\n') + 2]
for family in ('mainElems', 'appsMainElems', 'favsMainElems', 'vcdMainElems',
               'infoElems', 'appsInfoElems', 'favsInfoElems', 'vcdInfoElems'):
    assert f'addGUIElemSlot(themePath, themeConfig, newT, &newT->{family},' in load, family
assert 'thmViewScan(themeConfig, &viewInfo);' in load
assert load.index('thmParseViewPrefix = "";') > load.index('favsAppsInfo')
assert 'snprintf(path, sizeof(path), "main%d"' not in load  # no family bypasses the resolver


def strip_includes(text):
    return '\n'.join(line for line in text.splitlines() if not line.startswith('#include "'))


program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#define CONFIG_KEY_NAME_LEN @KEYLEN@
struct config_value_t {
    char key[CONFIG_KEY_NAME_LEN];
    char val[256];
    struct config_value_t *next;
};
typedef struct { struct config_value_t *head, *tail; } config_set_t;

static void configSetStr(config_set_t *c, const char *key, const char *val)
{
    struct config_value_t *v = calloc(1, sizeof(*v));
    strncpy(v->key, key, CONFIG_KEY_NAME_LEN - 1); // truncates like config.c
    strncpy(v->val, val, sizeof(v->val) - 1);
    if (c->tail) c->tail->next = v; else c->head = v;
    c->tail = v;
}
int configGetStr(config_set_t *c, const char *key, const char **value)
{
    if (c == NULL) return 0;
    for (struct config_value_t *v = c->head; v; v = v->next)
        if (!strncmp(v->key, key, CONFIG_KEY_NAME_LEN)) { *value = v->val; return 1; }
    return 0;
}
int configGetInt(config_set_t *c, const char *key, int *value)
{
    const char *s;
    if (!configGetStr(c, key, &s)) return 0;
    *value = atoi(s);
    return 1;
}
int configGetColor(config_set_t *c, const char *key, unsigned char *color)
{
    const char *s;
    if (!configGetStr(c, key, &s) || s[0] != '#') return 0;
    unsigned int rgb = (unsigned int)strtoul(s + 1, NULL, 16);
    color[0] = rgb >> 16; color[1] = rgb >> 8; color[2] = rgb;
    return 1;
}
// Legacy theme syntax: "name:" opens a section, indented "key=value" lines become "name_key", and an
// unindented line closes the section (src/config.c configRead).
static config_set_t *parse(const char *text)
{
    config_set_t *c = calloc(1, sizeof(*c));
    char line[512], prefix[CONFIG_KEY_NAME_LEN] = "", composed[2 * CONFIG_KEY_NAME_LEN];
    while (*text) {
        size_t n = strcspn(text, "\n");
        memcpy(line, text, n); line[n] = 0;
        text += n + (text[n] == '\n');
        char *eq = strchr(line, '=');
        if (eq) {
            *eq = 0;
            char *key = line;
            if (*key != '\t' && *key != ' ') prefix[0] = 0;
            while (*key == '\t' || *key == ' ') key++;
            if (prefix[0]) { snprintf(composed, sizeof(composed), "%s_%s", prefix, key); configSetStr(c, composed, eq + 1); }
            else configSetStr(c, key, eq + 1);
        } else if (strchr(line, ':')) {
            *strchr(line, ':') = 0;
            snprintf(prefix, sizeof(prefix), "%s", line);
        }
    }
    return c;
}
static void configFree(config_set_t *c)
{
    struct config_value_t *v = c->head;
    while (v) { struct config_value_t *n = v->next; free(v); v = n; }
    free(c);
}
@HEADER@
@SOURCE@
static const char *slot(config_set_t *c, const char *prefix, const char *const *chain, int chainLen, int j)
{
    static char name[THM_VIEW_BLOCK_NAME_LEN];
    return thmViewResolveSlot(c, prefix, 1, chain, chainLen, j, name, sizeof(name)) ? name : "<none>";
}
#define SLOT(c, p, ch, n, j, want) assert(!strcmp(slot(c, p, ch, n, j), want))
int main(void)
{
    static const char *const mainChain[] = {"main"};
    static const char *const appsChain[] = {"appsMain", "main"};
    static const char *const vcdChain[] = {"vcdMain", "appsMain", "main"};
    thm_view_info_t info;

    assert(thmViewFromName("Coverflow") == THM_VIEW_COVERFLOW && thmViewFromName("psbbn") == THM_VIEW_PSBBN);
    assert(thmViewFromName("bogus") == -1 && thmViewFromName(NULL) == -1);
    assert(!strcmp(thmViewName(THM_VIEW_GRID), "grid") && !strcmp(thmViewName(9), ""));
    assert(thmViewFromLegacyTheme("<Coverflow>") == THM_VIEW_COVERFLOW && thmViewFromLegacyTheme("<psbbn flow>") == THM_VIEW_PSBBN);
    assert(thmViewFromLegacyTheme("<OPL>") == -1 && thmViewFromLegacyTheme(NULL) == -1);

    // A theme without views: List, no prefix, base resolution exactly as before.
    config_set_t *plain = parse("main0:\n\ttype=Background\nmain1:\n\ttype=ItemsList\nappsMain1:\n\ttype=ItemCover\n"
                                "main2:\n\ttype=StaticImage\nmain3_enabled=0\n");
    thmViewScan(plain, &info);
    assert(info.native == THM_VIEW_LIST && info.mask == (1u << THM_VIEW_LIST) && info.blocksMask == 0);
    assert(thmViewChoose(&info, THM_VIEW_COVERFLOW) == THM_VIEW_LIST); // not offered -> default
    assert(!strcmp(thmViewPrefix(&info, THM_VIEW_LIST), ""));
    SLOT(plain, "", mainChain, 1, 1, "main1");
    SLOT(plain, "", appsChain, 2, 1, "appsMain1");
    SLOT(plain, "", appsChain, 2, 2, "main2");
    SLOT(plain, "", mainChain, 1, 3, "main3"); // switched off is still present
    SLOT(plain, "", mainChain, 1, 4, "<none>");
    configFree(plain);

    // A legacy single-view flow theme: native view from its element type.
    config_set_t *flow = parse("main0:\n\ttype=Background\nmain1:\n\ttype=PSBBNFlow\n");
    thmViewScan(flow, &info);
    assert(info.native == THM_VIEW_PSBBN && info.mask == (1u << THM_VIEW_PSBBN) && info.defaultView == THM_VIEW_PSBBN);
    configFree(flow);
    config_set_t *gridTheme = parse("main0:\n\ttype=Background\nmain1:\n\ttype=Grid\n");
    thmViewScan(gridTheme, &info);
    assert(info.native == THM_VIEW_GRID && info.mask == (1u << THM_VIEW_GRID));
    configFree(gridTheme);

    // A multi-view theme.
    config_set_t *mv = parse("views=list, coverflow,grid\n"
                             "default_view=coverflow\n"
                             "text_color=#101010\n"
                             "coverflow.text_color=#202020\n"
                             "use_default=1\n"
                             "main0:\n\ttype=Background\n"
                             "main1:\n\ttype=ItemsList\n"
                             "main2:\n\ttype=ItemCover\n"
                             "appsMain2:\n\ttype=ItemCover\n"
                             "coverflow.main2:\n\ttype=Coverflow\n"
                             "coverflow.main1_enabled=0\n"
                             "coverflow.main3:\n\ttype=StaticText\n"
                             "psbbn.main2:\n\ttype=PSBBNFlow\n"
                             "favsVcdMain12:\n\treflection_offset=1\n"
                             "coverflow.favsVcdMain12:\n\treflection_offset=2\n");
    thmViewScan(mv, &info);
    assert(info.native == THM_VIEW_LIST);
    assert(info.mask == ((1u << THM_VIEW_LIST) | (1u << THM_VIEW_COVERFLOW) | (1u << THM_VIEW_GRID))); // views= wins
    assert(info.blocksMask == ((1u << THM_VIEW_COVERFLOW) | (1u << THM_VIEW_PSBBN)));
    assert(info.defaultView == THM_VIEW_COVERFLOW);
    assert(thmViewChoose(&info, -1) == THM_VIEW_COVERFLOW && thmViewChoose(&info, THM_VIEW_LIST) == THM_VIEW_LIST);
    assert(thmViewChoose(&info, THM_VIEW_PSBBN) == THM_VIEW_COVERFLOW); // not in views=
    assert(!strcmp(thmViewPrefix(&info, THM_VIEW_COVERFLOW), "coverflow"));
    assert(!strcmp(thmViewPrefix(&info, THM_VIEW_GRID), "")); // offered, but nothing declared for it

    // View blocks replace base blocks; the view prefix applies to the whole chain before the base.
    SLOT(mv, "coverflow", mainChain, 1, 2, "coverflow.main2");
    SLOT(mv, "coverflow", appsChain, 2, 2, "coverflow.main2"); // view main beats base appsMain
    SLOT(mv, "", appsChain, 2, 2, "appsMain2");
    SLOT(mv, "coverflow", vcdChain, 3, 2, "coverflow.main2");
    SLOT(mv, "coverflow", mainChain, 1, 1, "coverflow.main1"); // switched off in this view
    SLOT(mv, "coverflow", mainChain, 1, 0, "main0");           // inherited
    SLOT(mv, "coverflow", mainChain, 1, 3, "coverflow.main3"); // appended past the base
    SLOT(mv, "", mainChain, 1, 3, "<none>");
    SLOT(mv, "coverflow", mainChain, 1, 4, "<none>");

    // The longest prefixed key survives the key length and does not collide with the base key.
    int v = 0;
    assert(configGetInt(mv, "favsVcdMain12_reflection_offset", &v) && v == 1);
    assert(configGetInt(mv, "coverflow.favsVcdMain12_reflection_offset", &v) && v == 2);

    // View-scoped theme-wide keys.
    unsigned char col[3] = {0, 0, 0};
    assert(thmViewGetColor(mv, "coverflow", "text_color", col) && col[0] == 0x20);
    assert(thmViewGetColor(mv, "", "text_color", col) && col[0] == 0x10);
    assert(thmViewGetInt(mv, "coverflow", "use_default", &v) && v == 1);
    configFree(mv);

    // <view>.inherit=0: the view's blocks never fall back to the base.
    config_set_t *own = parse("main0:\n\ttype=Background\nmain1:\n\ttype=ItemsList\nmain2:\n\ttype=ItemCover\n"
                              "psbbn.inherit=0\npsbbn.main0:\n\ttype=Background\npsbbn.main1:\n\ttype=PSBBNFlow\n");
    thmViewScan(own, &info);
    assert(info.ownMask == (1u << THM_VIEW_PSBBN));
    assert(thmViewInheritsBase(&info, THM_VIEW_LIST) == 1 && thmViewInheritsBase(&info, THM_VIEW_PSBBN) == 0);
    char name[THM_VIEW_BLOCK_NAME_LEN];
    assert(thmViewResolveSlot(own, "psbbn", 0, mainChain, 1, 1, name, sizeof(name)) && !strcmp(name, "psbbn.main1"));
    assert(!thmViewResolveSlot(own, "psbbn", 0, mainChain, 1, 2, name, sizeof(name))); // base main2 not inherited
    assert(thmViewResolveSlot(own, "psbbn", 1, mainChain, 1, 2, name, sizeof(name)) && !strcmp(name, "main2"));
    assert(thmViewResolveSlot(own, "", 0, mainChain, 1, 2, name, sizeof(name)) && !strcmp(name, "main2")); // no prefix = base
    configFree(own);

    // default_view naming a view the theme does not offer falls back to the native view.
    config_set_t *bad = parse("views=coverflow,list\ndefault_view=grid\nmain0:\n\ttype=Coverflow\n");
    thmViewScan(bad, &info);
    assert(info.native == THM_VIEW_COVERFLOW && info.defaultView == THM_VIEW_COVERFLOW);
    configFree(bad);

    // views= with no known name is ignored.
    config_set_t *junk = parse("views=carousel\nmain0:\n\ttype=Background\n");
    thmViewScan(junk, &info);
    assert(info.mask == (1u << THM_VIEW_LIST));
    configFree(junk);

    // Key prefixes are matched exactly: blocks are looked up as "<lowercase view>.<key>", so a mixed-case
    // prefix declares no view and its inherit=0 does not strip the base.
    config_set_t *mixed = parse("main0:\n\ttype=Background\nCoverflow.inherit=0\nCoverflow.main1:\n\ttype=Coverflow\n");
    thmViewScan(mixed, &info);
    assert(info.blocksMask == 0 && info.ownMask == 0 && info.mask == (1u << THM_VIEW_LIST));
    configFree(mixed);

    // No config at all (a theme folder without conf_theme.cfg) is a plain List theme.
    thmViewScan(NULL, &info);
    assert(info.native == THM_VIEW_LIST && info.mask == (1u << THM_VIEW_LIST) && info.defaultView == THM_VIEW_LIST);

    puts("themeviews: view names, legacy names, scan, choice, prefixes, slot chains, inherit=0, scoped keys and key length passed");
    return 0;
}
'''

program = (program.replace('@KEYLEN@', str(KEY_LEN))
           .replace('@HEADER@', strip_includes(HEADER))
           .replace('@SOURCE@', strip_includes(SOURCE)))

with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    source = folder / 'themeviews.c'
    binary = folder / ('themeviews' + ('.exe' if os.name == 'nt' else ''))
    source.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-format-truncation',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
