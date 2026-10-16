"""Compile parental-lock policy and Test Changes launch against controlled UI/config.

Checks cancellation, incorrect/correct/master passwords, repeated game prompts,
settings-unlock independence, unsaved lock removal, newly locked test configs,
allocation failure, and command-line launch integration guards.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
menu = (root / 'src/menusys.c').read_text(encoding='utf-8')
game = (root / 'src/guigame.c').read_text(encoding='utf-8')
opl = (root / 'src/opl.c').read_text(encoding='utf-8')

def function(source, sig):
    start = source.index(sig)
    return source[start:source.index('\n}', start)+2]

helpers = '\n'.join(function(menu, sig) for sig in (
    'static const char *menuGetParentalLockPassword(', 'int menuIsParentalLockPasswordSet(',
    'static int menuPromptParentalLockPassword(', 'int menuCheckParentalLock(',
    'int menuGameRequiresParentalLock(', 'int menuCheckGameParentalLock('))
select = function(opl, 'static void itemExecSelect(')
assert select.index('menuCheckGameParentalLock(configSet)') < select.index('guiGameAutoCreateVmc(') < select.index('support->itemLaunch(')
assert 'strcmp(startup, gameIdStartup) == 0' in select[select.index('menuCheckGameParentalLock('):select.index('guiGameAutoCreateVmc(')]
for name, launch in [('autoLaunchHDDGame', 'hddLaunchGame'), ('autoLaunchBDMGame', 'bdmLaunchGame')]:
    source = function(opl, 'static void '+name+'(')
    assert 'if (!menuGameRequiresParentalLock(configSet))\n        '+launch+'(NULL, -1, configSet);' in source
    assert 'miniDeinit(configSet);' in source
# Favorites retain the selected game's config when forwarding to its owner.
fav = function((root / 'src/favsupport.c').read_text(encoding='utf-8'), 'static void favLaunchItem(')
assert 'o->itemLaunch(o, favArray[id].id, configSet);' in fav
save_branch = menu[menu.index('} else if (menuID == GAME_SAVE_CHANGES)'):menu.index('} else if (menuID == GAME_TEST_CHANGES)')]
assert save_branch.index('if (changed < 0)') < save_branch.index('menuSaveConfig()')
assert 'menuGameRequiresParentalLock(configSet) ? menuCheckGameParentalLock(configSet)' in function(game, 'void guiGameRemoveSettings(')
main_input = function(menu, 'void menuHandleInputMain(')
assert 'DisableCron == 0' in main_input and 'DisableCron = 1;' in main_input
harness = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define CONFIG_OPL 1
#define CONFIG_KEY_VALUE_LEN 64
#define CONFIG_OPL_PARENTAL_LOCK_PWD 1
#define CONFIG_ITEM_PARENTAL_LOCK 2
#define COMPAT_PARENTAL_LOCK 3
#define diaCompatConfig 1
#define OPL_PARENTAL_LOCK_MASTER_PASS "989765"
#define _STR_PARENLOCK_ENTER_PASSWORD_TITLE 3
#define _STR_PARENLOCK_DISABLE_WARNING 4
#define _STR_PARENLOCK_PASSWORD_INCORRECT 5
#define _l(x) (x)
typedef struct {int locked;char password[64];} config_set_t;
static config_set_t global, cloned;
static int parentalLockCheckEnabled=1, prompts, accept=1, notices, saved, launches, edits, frees, failClone, editLock;
static const char *answer;
static config_set_t *configGetByType(int type) {assert(type==CONFIG_OPL);return &global;}
static int configGetStr(config_set_t *c,int key,const char **out) {assert(key==1);*out=c->password;return 1;}
static int configGetInt(config_set_t *c,int key,int *out) {assert(key==2);*out=c->locked;return 1;}
static void configRemoveKey(config_set_t *c,int key) {assert(key==1);c->password[0]=0;}
static int diaShowKeyb(char *out,int size,int hidden,int title) {
    assert(size==64 && hidden && title==3);prompts++;snprintf(out,size,"%s",answer);return accept;
}
static void guiMsgBox(int text,int flags,void *callback) {(void)text;(void)flags;(void)callback;notices++;}
static void saveConfig(int type,int flags) {assert(type==1 && flags==1);saved++;}
@HELPERS@
typedef struct item_list {void (*itemLaunch)(struct item_list *,int,config_set_t *);} item_list_t;
static config_set_t *configClone(config_set_t *c) {if(failClone)return NULL;cloned=*c;return &cloned;}
static void configFree(config_set_t *c) {assert(c==&cloned);frees++;}
static int guiGameApplyConfig(config_set_t *c,item_list_t *s) {(void)s;edits++;c->locked=editLock;return 1;}
static void launch(item_list_t *s,int id,config_set_t *c) {(void)s;(void)c;assert(id==7);launches++;}
static void diaGetInt(int dialog,int key,int *out) {assert(dialog==1&&key==3);*out=editLock;}
@SAVE_CONFIG@
@TEST_LAUNCH@
static void reset(void) {
    memset(&global,0,sizeof(global));strcpy(global.password,"secret");
    answer="secret";accept=1;parentalLockCheckEnabled=1;
    prompts=notices=saved=launches=edits=frees=failClone=editLock=0;
}
int main(void) {
    config_set_t locked={1,""},unlocked={0,""};item_list_t support={launch};
    reset();assert(!menuCheckGameParentalLock(&unlocked) && !prompts);
    assert(!menuCheckGameParentalLock(NULL) && !prompts);
    assert(menuGameRequiresParentalLock(&locked));
    assert(!menuCheckParentalLock() && prompts==1 && !parentalLockCheckEnabled);
    assert(!menuCheckGameParentalLock(&locked) && prompts==2);
    assert(!menuCheckGameParentalLock(&locked) && prompts==3);
    accept=0;assert(menuCheckGameParentalLock(&locked)==EACCES);
    accept=1;answer="wrong";assert(menuCheckGameParentalLock(&locked)==EACCES);
    answer=OPL_PARENTAL_LOCK_MASTER_PASS;assert(!menuCheckGameParentalLock(&locked));
    assert(!global.password[0] && saved==1 && !menuGameRequiresParentalLock(&locked));
    reset();accept=0;editLock=0;guiGameTestSettings(7,&support,&locked);
    assert(!launches && !edits && locked.locked==1); /* unsaved unlock cannot bypass stored lock */
    reset();editLock=0;guiGameTestSettings(7,&support,&locked);
    assert(launches==1 && prompts==1 && edits==1 && frees==1 && locked.locked==1);
    reset();editLock=1;accept=0;guiGameTestSettings(7,&support,&unlocked);
    assert(!launches && prompts==1 && frees==1 && unlocked.locked==0);
    reset();editLock=1;guiGameTestSettings(7,&support,&unlocked);
    assert(launches==1 && prompts==1 && unlocked.locked==0);
    reset();failClone=1;editLock=0;accept=0;guiGameTestSettings(7,&support,&locked);
    assert(!launches && !edits && locked.locked==1);
    reset();failClone=1;editLock=0;guiGameTestSettings(7,&support,&locked);
    assert(!launches && !edits && locked.locked==1 && prompts==1);
    reset();failClone=1;editLock=1;guiGameTestSettings(7,&support,&unlocked);
    assert(!launches && !edits && unlocked.locked==0);
    reset();answer="wrong";editLock=0;assert(guiGameSaveConfig(&locked,&support)<0);
    assert(locked.locked==1 && edits==0 && prompts==1);
    reset();accept=0;editLock=0;assert(guiGameSaveConfig(&locked,&support)<0);
    assert(locked.locked==1 && edits==0);
    reset();editLock=0;assert(guiGameSaveConfig(&locked,&support)>0);
    assert(locked.locked==0 && edits==1 && prompts==1);locked.locked=1;
    reset();editLock=1;assert(guiGameSaveConfig(&locked,&support)>0);
    assert(locked.locked==1 && edits==1 && prompts==0);
    reset();global.password[0]=0;assert(!menuGameRequiresParentalLock(&locked));
    assert(!menuCheckGameParentalLock(&locked) && !prompts);
    puts("PASS: repeated prompts, cancel/wrong/master passwords, test edits and autolaunch guards");
}
""".replace('@HELPERS@', helpers).replace('@SAVE_CONFIG@', function(game, 'int guiGameSaveConfig(')).replace('@TEST_LAUNCH@', function(game, 'void guiGameTestSettings('))
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'parental.c'
    path.write_text(harness,encoding='utf-8')
    binary = path.with_suffix('.exe')
    flags=['-std=gnu99','-Wall','-Wextra','-Werror']
    if os.name != 'nt':
        flags += ['-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie']
    subprocess.run([os.environ.get('CC','gcc'),*flags,str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
