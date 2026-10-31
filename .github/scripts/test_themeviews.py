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
#define CONFIG_KEY_VALUE_LEN 256
struct config_value_t {
    char key[CONFIG_KEY_NAME_LEN];
    char val[256];
    struct config_value_t *next;
};
typedef struct { struct config_value_t *head, *tail; } config_set_t;

static void configSetStr(config_set_t *c, const char *key, const char *val)
{
    for (struct config_value_t *e = c->head; e; e = e->next) // an existing key is overwritten, as in config.c
        if (!strncmp(e->key, key, CONFIG_KEY_NAME_LEN - 1)) { strncpy(e->val, val, sizeof(e->val) - 1); return; }
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

    // SD/HD layouts: _sd/_hd variants and the uOPL/wOPL _wsX key.
    {
        static const char *layout = "bg_color=#000000\n"
                                    "bg_color_hd=#101010\n"
                                    "main1:\n\ttype=StaticImage\n\tx=100\n\ty=50\n\tx_hd=140\n\ty_hd=60\n"
                                    "main2:\n\ttype=StaticImage\n\tx=200\n\twsX=-150\n"
                                    "main3:\n\ttype=StaticImage\n\tx=300\n\twsX=310\n\tx_hd=320\n"
                                    "main4:\n\ttype=StaticImage\n\tx=400\n\tx_sd=410\n"
                                    "coverflow.main5:\n\ttype=Coverflow\n\ty=240\n\ty_hd=250\n";
        const char *s;
        int i;

        config_set_t *sd = parse(layout);
        assert(thmApplyDisplayLayout(sd, 0) == 1);
        assert(configGetInt(sd, "main1_x", &i) && i == 100);
        assert(configGetInt(sd, "main1_y", &i) && i == 50);
        assert(configGetInt(sd, "main2_x", &i) && i == 200); // _wsX is for 16:9 only
        assert(configGetInt(sd, "main4_x", &i) && i == 410); // _sd wins in 4:3
        assert(configGetStr(sd, "bg_color", &s) && !strcmp(s, "#000000"));
        assert(configGetInt(sd, "coverflow.main5_y", &i) && i == 240);
        configFree(sd);

        config_set_t *hd = parse(layout);
        assert(thmApplyDisplayLayout(hd, 1) == 1);
        assert(configGetInt(hd, "main1_x", &i) && i == 140);
        assert(configGetInt(hd, "main1_y", &i) && i == 60);
        assert(configGetInt(hd, "main2_x", &i) && i == -150); // negative = from the right edge, as for x
        assert(configGetInt(hd, "main3_x", &i) && i == 320);  // x_hd beats wsX
        assert(configGetInt(hd, "main4_x", &i) && i == 400);  // no _hd: the plain key
        assert(configGetStr(hd, "bg_color", &s) && !strcmp(s, "#101010"));
        assert(configGetInt(hd, "coverflow.main5_y", &i) && i == 250); // works under a view prefix
        assert(configGetInt(hd, "main1_x_hd", &i) && i == 140);       // the variant keys stay readable
        configFree(hd);

        // A theme without variants reports none and is left exactly as read.
        config_set_t *none = parse("main0:\n\ttype=Background\nmain1:\n\ttype=StaticImage\n\tx=12\n");
        int before = 0, after = 0;
        for (struct config_value_t *e = none->head; e; e = e->next)
            before++;
        assert(thmApplyDisplayLayout(none, 1) == 0);
        for (struct config_value_t *e = none->head; e; e = e->next)
            after++;
        assert(before == after);
        assert(configGetInt(none, "main1_x", &i) && i == 12);
        configFree(none);
        assert(thmApplyDisplayLayout(NULL, 1) == 0);

        // A variant whose plain key is missing creates it: an element can exist in one mode only.
        config_set_t *only = parse("main6_type_hd=StaticText\n");
        assert(thmApplyDisplayLayout(only, 0) == 1 && !configGetStr(only, "main6_type", &s));
        configFree(only);
        only = parse("main6_type_hd=StaticText\n");
        assert(thmApplyDisplayLayout(only, 1) == 1 && configGetStr(only, "main6_type", &s) && !strcmp(s, "StaticText"));
        configFree(only);

        // Alternate background (alt=).
        static const char *alts = "alt=bg_top\n"
                                  "main0:\n\ttype=Background\n\tdefault=bg\n\talt=bg_night\n"
                                  "main1:\n\ttype=Background\n\tdefault=bg2\n"
                                  "main2:\n\ttype=StaticImage\n\tdefault=logo\n"
                                  "coverflow.main0:\n\ttype=Background\n\tdefault=cf\n";
        config_set_t *off = parse(alts);
        assert(thmApplyAltBackground(off, 0) == 1); // declared, setting off: nothing changes
        assert(configGetStr(off, "main0_default", &s) && !strcmp(s, "bg"));
        assert(configGetStr(off, "main1_default", &s) && !strcmp(s, "bg2"));
        configFree(off);

        config_set_t *on = parse(alts);
        assert(thmApplyAltBackground(on, 1) == 1);
        assert(configGetStr(on, "main0_default", &s) && !strcmp(s, "bg_night"));          // its own alt= wins
        assert(configGetStr(on, "main1_default", &s) && !strcmp(s, "bg_top"));            // the top-level alt=
        assert(configGetStr(on, "main2_default", &s) && !strcmp(s, "logo"));              // not a Background
        assert(configGetStr(on, "coverflow.main0_default", &s) && !strcmp(s, "bg_top"));  // view blocks too
        configFree(on);

        // No Background block: the one added at load ("bg") takes the top-level alt=; its own bg_alt= wins.
        config_set_t *nobg = parse("alt=bg_top\nmain0:\n\ttype=StaticImage\n\tdefault=logo\n");
        assert(thmApplyAltBackground(nobg, 1) == 1 && configGetStr(nobg, "bg_default", &s) && !strcmp(s, "bg_top"));
        configFree(nobg);
        nobg = parse("alt=bg_top\nbg_alt=bg_own\n");
        assert(thmApplyAltBackground(nobg, 1) == 1 && configGetStr(nobg, "bg_default", &s) && !strcmp(s, "bg_own"));
        configFree(nobg);
        nobg = parse("alt=bg_top\n");
        assert(thmApplyAltBackground(nobg, 0) == 1 && !configGetStr(nobg, "bg_default", &s));
        configFree(nobg);

        config_set_t *plasma = parse("main0:\n\ttype=Background\n\talt=bg_night\n");
        assert(thmApplyAltBackground(plasma, 1) == 1 && configGetStr(plasma, "main0_default", &s) && !strcmp(s, "bg_night"));
        configFree(plasma);

        config_set_t *althd = parse("main0:\n\ttype=Background\n\tdefault=bg\n\talt=night\n\talt_hd=night_wide\n");
        thmApplyDisplayLayout(althd, 1);
        assert(thmApplyAltBackground(althd, 1) == 1 && configGetStr(althd, "main0_default", &s) && !strcmp(s, "night_wide"));
        configFree(althd);

        config_set_t *plain = parse("main0:\n\ttype=Background\n\tdefault=bg\nmain1:\n\ttype=StaticImage\n\tx=12\n");
        before = after = 0;
        for (struct config_value_t *e = plain->head; e; e = e->next)
            before++;
        assert(thmApplyAltBackground(plain, 1) == 0);
        for (struct config_value_t *e = plain->head; e; e = e->next)
            after++;
        assert(before == after && configGetStr(plain, "main0_default", &s) && !strcmp(s, "bg"));
        configFree(plain);
        assert(thmApplyAltBackground(NULL, 1) == 0);

        // hd_autofit: the 4:3 layout scaled by 3/4 about the centre.
        assert(thmLayoutAutoFitX(320, 640) == 320);
        assert(thmLayoutAutoFitX(0, 640) == 80);
        assert(thmLayoutAutoFitX(640, 640) == 560);
        assert(thmLayoutAutoFitX(100, 640) == 155);
    }

    // Fallback views: a theme without views= gets every view, built from its own layout.
    {
        config_set_t *lv = parse("views=list,coverflow\nmain0:\n\ttype=Background\n");
        thmViewScan(lv, &info);
        assert(info.listed == 1);
        configFree(lv);

        static const char *listTheme = "main0:\n\ttype=Background\n\tdefault=bg\n"
                                       "main1:\n\ttype=MenuIcon\n\tx=40\n"
                                       "main2:\n\ttype=ItemsList\n\tx=20\n\ty=60\n\twidth=380\n\theight=330\n\tfont=1\n"
                                       "main3:\n\ttype=ItemCover\n\tdefault=cover\n\tx=-120\n"
                                       "main4:\n\ttype=StaticText\n\tvalue=Hi\n"
                                       "main5_enabled=0\n"
                                       "appsMain3:\n\ttype=ItemCover\n\tdefault=coverapp\n"
                                       "info0:\n\ttype=Background\n";
        static const char *cfTemplate = "main0:\n\ttype=Background\n"
                                        "main2:\n\ttype=Coverflow\n\tdefault=cover\n\ty=233\n\twidth=184\n"
                                        "appsMain2:\n\ttype=Coverflow\n\tdefault=coverapp\n\ty=239\n"
                                        "vcdMain2:\n\ttype=Coverflow\n\tdefault=cover\n"
                                        "main15:\n\ttype=ItemsList\n\tx=POS_MID\n\ty=45\n\twidth=DIM_INF\n\theight=24\n\taligned=1\n";
        config_set_t *t = parse(listTheme);
        config_set_t *tmpl = parse(cfTemplate);
        thmViewScan(t, &info);
        assert(info.listed == 0 && info.mask == (1u << THM_VIEW_LIST));
        assert(thmViewSynthesize(t, tmpl, THM_VIEW_COVERFLOW) == 1);
        const char *s;
        int i;
        SLOT(t, "coverflow", mainChain, 1, 0, "coverflow.main0");
        assert(configGetStr(t, "coverflow.main0_default", &s) && !strcmp(s, "bg"));       // the theme's own background
        assert(configGetStr(t, "coverflow.main3_type", &s) && !strcmp(s, "Coverflow"));   // cover -> carousel, same slot
        assert(configGetInt(t, "coverflow.main3_y", &i) && i == 233);
        assert(!configGetStr(t, "coverflow.main3_x", &s));                                // no stale key from the ItemCover
        assert(configGetStr(t, "coverflow.main2_y", &s) && !strcmp(s, "45"));            // list moved to the title strip
        assert(configGetStr(t, "coverflow.main2_width", &s) && !strcmp(s, "DIM_INF"));
        assert(configGetInt(t, "coverflow.main2_font", &i) && i == 1);                   // keeps its own font
        assert(configGetStr(t, "coverflow.main4_value", &s) && !strcmp(s, "Hi"));
        assert(configGetInt(t, "coverflow.main5_enabled", &i) && i == 0);
        assert(configGetStr(t, "coverflow.appsMain3_default", &s) && !strcmp(s, "coverapp")); // apps template
        assert(configGetInt(t, "coverflow.appsMain3_y", &i) && i == 239);
        assert(configGetStr(t, "coverflow.vcdMain3_type", &s) && !strcmp(s, "Coverflow")); // PS1 gets its own
        assert(!configGetStr(t, "coverflow.info0_type", &s));                               // info pages untouched
        assert(configGetStr(t, "main3_type", &s) && !strcmp(s, "ItemCover"));             // base left as is
        configFree(t);

        // A list-only theme without a cover: the presenter goes after its last main block.
        t = parse("main0:\n\ttype=Background\nmain1:\n\ttype=ItemsList\n");
        assert(thmViewSynthesize(t, tmpl, THM_VIEW_COVERFLOW) == 1);
        assert(configGetStr(t, "coverflow.main2_type", &s) && !strcmp(s, "Coverflow"));
        SLOT(t, "coverflow", mainChain, 1, 2, "coverflow.main2");
        configFree(t);

        // A template without the presenter builds nothing.
        config_set_t *empty = parse("main0:\n\ttype=Background\n");
        t = parse(listTheme);
        assert(thmViewSynthesize(t, empty, THM_VIEW_GRID) == 0);
        assert(!configGetStr(t, "grid.main0_type", &s));
        configFree(t);
        configFree(empty);
        configFree(tmpl);
    }

    // Coverflow (3) and Coverflow (5): one theme view, two picks.
    {
        int covers = 3, p, view;
        unsigned int all = (1u << THM_VIEW_COUNT) - 1, cf = 1u << THM_VIEW_COVERFLOW;
        assert(thmViewPickFor(-1, 5) == THM_VIEW_PICK_DEFAULT);
        assert(thmViewPickFor(THM_VIEW_LIST, 5) == THM_VIEW_PICK_LIST);
        assert(thmViewPickFor(THM_VIEW_COVERFLOW, 3) == THM_VIEW_PICK_COVERFLOW3);
        assert(thmViewPickFor(THM_VIEW_COVERFLOW, 5) == THM_VIEW_PICK_COVERFLOW5);
        assert(thmViewPickFor(THM_VIEW_COVERFLOW, 7) == THM_VIEW_PICK_COVERFLOW3); // hand-edited count
        assert(thmViewPickFor(THM_VIEW_GRID, 3) == THM_VIEW_PICK_GRID);
        assert(thmViewPickRequest(THM_VIEW_PICK_COVERFLOW5, &covers) == THM_VIEW_COVERFLOW && covers == 5);
        assert(thmViewPickRequest(THM_VIEW_PICK_PSBBN, &covers) == THM_VIEW_PSBBN && covers == 5); // kept
        assert(thmViewPickRequest(THM_VIEW_PICK_COVERFLOW3, &covers) == THM_VIEW_COVERFLOW && covers == 3);
        assert(thmViewPickRequest(THM_VIEW_PICK_DEFAULT, &covers) == -1 && covers == 3);
        assert(thmViewPickRequest(99, &covers) == -1);
        for (p = THM_VIEW_PICK_LIST; p < THM_VIEW_PICK_COUNT; p++) {
            int c = 3;
            int r = thmViewPickRequest(p, &c);
            assert(thmViewPickFor(r, c) == p);
        }

        // Hold L3 walks List, Coverflow (3), Coverflow (5), PSBBN Flow, Grid, List.
        view = THM_VIEW_LIST;
        covers = 5;
        view = thmViewCycleNext(all, view, &covers);
        assert(view == THM_VIEW_COVERFLOW && covers == 3);
        view = thmViewCycleNext(all, view, &covers);
        assert(view == THM_VIEW_COVERFLOW && covers == 5);
        view = thmViewCycleNext(all, view, &covers);
        assert(view == THM_VIEW_PSBBN && covers == 5);
        view = thmViewCycleNext(all, view, &covers);
        assert(view == THM_VIEW_GRID);
        assert(thmViewCycleNext(all, view, &covers) == THM_VIEW_LIST);

        // A Coverflow-only theme still toggles 3 and 5; a List-only theme has nothing to cycle.
        covers = 3;
        assert(thmViewCycleNext(cf, THM_VIEW_COVERFLOW, &covers) == THM_VIEW_COVERFLOW && covers == 5);
        assert(thmViewCycleNext(cf, THM_VIEW_COVERFLOW, &covers) == THM_VIEW_COVERFLOW && covers == 3);
        covers = 5;
        assert(thmViewCycleNext(1u << THM_VIEW_LIST, THM_VIEW_LIST, &covers) == THM_VIEW_LIST && covers == 5);
        assert(thmViewCycleNext((1u << THM_VIEW_LIST) | (1u << THM_VIEW_PSBBN), THM_VIEW_LIST, &covers) == THM_VIEW_PSBBN);
    }

    puts("themeviews: view names, legacy names, scan, choice, prefixes, slot chains, inherit=0, scoped keys, SD/HD layouts, fallback views, Coverflow (3)/(5) picks and key length passed");
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
