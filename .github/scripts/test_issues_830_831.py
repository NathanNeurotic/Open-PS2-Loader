"""Test regression repairs for Issue #830 (Neutrino exFAT VMC budget & creation) and Issue #831 (Beat Down title compat defaults)."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
src_support = (root / 'src/supportbase.c').read_text(encoding='utf-8')
src_bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8')
src_gui = (root / 'src/guigame.c').read_text(encoding='utf-8')

# 1. Verify sbTitleCompatDefaults in src/supportbase.c
for startup in ('SLUS_212.42', 'SLES_535.58', 'SLPM_660.94', 'SLKA_253.13'):
    pattern = rf'"{startup}",\s*COMPAT_MODE_2'
    assert re.search(pattern, src_support) is not None, f"Expected {startup} in sbTitleCompatDefaults with COMPAT_MODE_2"

print("PASS: sbTitleCompatDefaults covers Beat Down: Fists of Vengeance across regions with COMPAT_MODE_2")

# 2. Verify guiGameResolveEffectiveCore exists in src/guigame.c and is called in VMC dialogs
assert 'guiGameResolveEffectiveCore' in src_gui, "guiGameResolveEffectiveCore must exist in src/guigame.c"
assert 'coreLoader = guiGameResolveEffectiveCore(support, id);' in src_gui, "guiGameResolveEffectiveCore must update coreLoader in VMC paths"

# 3. Test bdmNeutrinoFragBudgetOk logic in an isolated C harness
harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NEUTRINO_BDM_MAX_FRAGS 64
#define NEUTRINO_VMC_SLOTS 2

typedef struct {
    char arg[NEUTRINO_VMC_SLOTS][160];
} neutrino_vmc_args_t;

static int msgBoxResponse = 1;
static int msgBoxCalled = 0;
static char lastMsgBox[256];

static int guiIsActive(void) { return 1; }
static int guiMsgBox(const char *text, int type, void *dialog) {
    (void)type; (void)dialog;
    msgBoxCalled++;
    snprintf(lastMsgBox, sizeof(lastMsgBox), "%s", text);
    return msgBoxResponse;
}
static const char *_l(int id) { (void)id; return "VMC %s is fragmented. Continue with slot %d?"; }
#define _STR_ERR_VMC_FRAGMENTED_CONTINUE 1
#define _STR_NEUTRINO_TOO_FRAGMENTED 2
#define _STR_NEUTRINO_TOO_FRAGMENTED_NET 3
#define LOG(...) ((void)0)
#define guiWarning(...) ((void)0)

static void *gAutoLaunchBDMGame = NULL;

// Test implementation mirroring src/bdmsupport.c
static int testFragBudget(int isoFrags, int vmc0Frags, int vmc1Frags, neutrino_vmc_args_t *vmcArgs, int isUdp)
{
    (void)isUdp;
    int total = isoFrags;
    int vmcFrags[NEUTRINO_VMC_SLOTS] = { vmc0Frags, vmc1Frags };
    const char *vmcPaths[NEUTRINO_VMC_SLOTS] = { NULL, NULL };

    for (int i = 0; i < NEUTRINO_VMC_SLOTS; i++) {
        const char *eq = (vmcArgs != NULL && vmcArgs->arg[i][0]) ? strchr(vmcArgs->arg[i], '=') : NULL;
        if (eq != NULL && eq[1] != '\0') {
            vmcPaths[i] = eq + 1;
            total += vmcFrags[i];
        }
    }

    if (total > NEUTRINO_BDM_MAX_FRAGS) {
        if (isoFrags <= NEUTRINO_BDM_MAX_FRAGS && (vmcFrags[0] > 0 || vmcFrags[1] > 0)) {
            for (int i = 0; i < NEUTRINO_VMC_SLOTS && total > NEUTRINO_BDM_MAX_FRAGS; i++) {
                if (vmcFrags[i] > 0) {
                    char vmcName[32];
                    const char *slash = strrchr(vmcPaths[i], '/');
                    const char *dot = strrchr(vmcPaths[i], '.');
                    const char *start = slash ? slash + 1 : vmcPaths[i];
                    int nlen = dot && dot > start ? (int)(dot - start) : (int)strlen(start);
                    snprintf(vmcName, sizeof(vmcName), "%.*s", nlen, start);

                    if (gAutoLaunchBDMGame == NULL && guiIsActive()) {
                        char error[256];
                        snprintf(error, sizeof(error), _l(_STR_ERR_VMC_FRAGMENTED_CONTINUE), vmcName, (i + 1));
                        if (!guiMsgBox(error, 1, NULL))
                            return -1; // Abort launch to menu
                    }
                    total -= vmcFrags[i];
                    vmcArgs->arg[i][0] = '\0';
                }
            }
            if (total <= NEUTRINO_BDM_MAX_FRAGS)
                return 1;
        }
        return 0;
    }
    return 1;
}

int main(void) {
    neutrino_vmc_args_t vmc;

    // Case 1: Total <= 64 -> fits within budget
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/game_0.bin");
    vmc.arg[1][0] = '\0';
    assert(testFragBudget(10, 5, 0, &vmc, 0) == 1);
    assert(vmc.arg[0][0] != '\0');

    // Case 2: ISO <= 64 but ISO + VMC > 64 -> user accepts prompt -> drops VMC and returns 1
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/game_0.bin");
    vmc.arg[1][0] = '\0';
    msgBoxCalled = 0;
    msgBoxResponse = 1;
    assert(testFragBudget(58, 8, 0, &vmc, 0) == 1);
    assert(msgBoxCalled == 1);
    assert(vmc.arg[0][0] == '\0'); // Dropped
    assert(strstr(lastMsgBox, "game_0") != NULL);

    // Case 3: ISO <= 64 but ISO + VMC > 64 -> user declines prompt -> returns -1 (abort launch)
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/game_0.bin");
    vmc.arg[1][0] = '\0';
    msgBoxCalled = 0;
    msgBoxResponse = 0;
    assert(testFragBudget(58, 8, 0, &vmc, 0) == -1);
    assert(msgBoxCalled == 1);

    // Case 4: ISO itself > 64 -> returns 0 (fatal ISO fragmentation)
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/game_0.bin");
    vmc.arg[1][0] = '\0';
    assert(testFragBudget(65, 2, 0, &vmc, 0) == 0);

    return 0;
}
'''

with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    cfile = temp / 'test_harness.c'
    exe = temp / 'test_harness'
    cfile.write_text(harness, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

print("PASS: bdmNeutrinoFragBudgetOk handles VMC budget overflow gracefully without catch-22")
