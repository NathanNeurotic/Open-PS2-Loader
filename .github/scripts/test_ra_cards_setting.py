"""Exercise the real experimental-card config reader and its dialog wiring."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
opl = (root / 'src/opl.c').read_text()
config = (root / 'src/config.c').read_text()


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


reader = function(opl, 'static void configReadRAExperimentalCards(')
get_int = function(config, 'int configGetInt(')
set_int = function(config, 'int configSetInt(')
gui = (root / 'src/gui.c').read_text()
start = gui.index('        int raMode, raTelemetry;')
control = gui[start:gui.index('#endif', start)]
program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int present; char value[32]; } config_set_t;
#define CONFIG_OPL_RA_EXPERIMENTAL_CARDS "ra_experimental_cards"
static int gRAExperimentalCards;
static int configGetStr(config_set_t *c, const char *key, const char **out) {
    assert(!strcmp(key, CONFIG_OPL_RA_EXPERIMENTAL_CARDS));
    if (!c->present) return 0;
    *out=c->value; return 1;
}
static int configSetStr(config_set_t *c, const char *key, const char *value) {
    assert(!strcmp(key, CONFIG_OPL_RA_EXPERIMENTAL_CARDS));
    snprintf(c->value,sizeof(c->value),"%s",value); c->present=1; return 1;
}
''' + get_int + '\n' + set_int + '\n' + reader + r'''
enum { NETCFG_RA_MODE, NETCFG_RA_TELEMETRY, NETCFG_RA_EXPERIMENTAL_CARDS };
#define RA_MODE_CADUCEUS 1
static int diaNetConfig, mode, telemetry, enabled;
static void diaGetInt(int dialog, int id, int *out) {
    (void)dialog;
    assert(id==NETCFG_RA_MODE || id==NETCFG_RA_TELEMETRY);
    *out=id==NETCFG_RA_MODE ? mode : telemetry;
}
static void diaSetEnabled(int dialog, int id, int value) {
    (void)dialog; assert(id==NETCFG_RA_EXPERIMENTAL_CARDS); enabled=value;
}
static void update(void) {
''' + control + r'''
}
int main(void) {
    config_set_t c={0};
    gRAExperimentalCards=1; configReadRAExperimentalCards(&c);
    assert(gRAExperimentalCards==0); /* old/missing config clears stale opt-in */
    assert(configSetInt(&c,CONFIG_OPL_RA_EXPERIMENTAL_CARDS,1));
    gRAExperimentalCards=0; configReadRAExperimentalCards(&c);
    assert(gRAExperimentalCards==1 && !strcmp(c.value,"1"));
    configSetInt(&c,CONFIG_OPL_RA_EXPERIMENTAL_CARDS,0);
    configReadRAExperimentalCards(&c); assert(!gRAExperimentalCards);
    const char *bad[]={"2","-1","99","garbage",""};
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        configSetStr(&c,CONFIG_OPL_RA_EXPERIMENTAL_CARDS,bad[i]);
        gRAExperimentalCards=1; configReadRAExperimentalCards(&c);
        assert(!gRAExperimentalCards);
    }
    for(mode=0;mode<=1;mode++) for(telemetry=0;telemetry<=1;telemetry++) {
        gRAExperimentalCards=1; enabled=-1; update();
        assert(enabled==(mode==1 && telemetry==1));
        assert(gRAExperimentalCards==1); /* inactive mode preserves saved choice */
    }
    puts("PASS: cards default Off, persist explicit opt-in, reload Off and reject non-boolean integers");
}
'''
with tempfile.TemporaryDirectory() as temp:
    source = Path(temp) / 'cards.c'
    exe = Path(temp) / 'cards.exe'
    source.write_text(program)
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                    str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# Both interactive settings reload and command-line autolaunch use the reader.
assert opl.count('configReadRAExperimentalCards(configOPL);') == 2
assert 'gRAExperimentalCards = 0;' in opl[opl.index('gRABadges = 1;'):]
assert 'configSetInt(configOPL, CONFIG_OPL_RA_EXPERIMENTAL_CARDS, gRAExperimentalCards);' in opl
assert 'diaSetInt(diaNetConfig, NETCFG_RA_EXPERIMENTAL_CARDS, gRAExperimentalCards);' in gui
assert 'diaGetInt(diaNetConfig, NETCFG_RA_EXPERIMENTAL_CARDS, &gRAExperimentalCards);' in gui
assert 'raMode == RA_MODE_CADUCEUS && raTelemetry' in gui
dialogs = (root / 'src/dialogs.c').read_text()
assert '{UI_BOOL, NETCFG_RA_EXPERIMENTAL_CARDS, 1, 1, _STR_HINT_RA_EXPERIMENTAL_CARDS, 0, 0, {.intvalue = {0, 0}}}' in dialogs
print('PASS: interactive/autolaunch reader, config save, dialog load/apply and Caduceus-only control')
