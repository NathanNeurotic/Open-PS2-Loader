"""Test regression repairs for Issue #830 (Neutrino exFAT VMC budget & creation) and Issue #831 (Beat Down title compat defaults)."""
from pathlib import Path
import json
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
src_support = (root / 'src/supportbase.c').read_text(encoding='utf-8')
src_bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8')
src_gui = (root / 'src/guigame.c').read_text(encoding='utf-8')

# 1. sbTitleCompatDefaults must not carry the serials #968 added for Beat Down. None of them is Beat Down
# (SLUS_212.42 is Burnout Revenge USA), so they forced Synchronous Reads on other games and never reached
# Beat Down itself (SLUS_211.50 / SLES_535.05 / SLPM_661.81 / SLPM_668.19 / SLPM_664.46). No real Beat Down
# serial gets a default either until a console test shows a mode that fixes the #831 hang.
table = src_support[src_support.index('sbTitleCompatDefaults[] = {'):]
table = table[:table.index('};')]
for startup in ('SLUS_212.42', 'SLES_535.58', 'SLPM_660.94', 'SLKA_253.13',
                'SLUS_211.50', 'SLES_535.05', 'SLPM_661.81', 'SLPM_668.19', 'SLPM_664.46'):
    assert f'"{startup}"' not in table, f"{startup} must not have a title compat default"

print("PASS: sbTitleCompatDefaults has no unverified Beat Down (#831) entries")

# 2. Verify guiGameResolveEffectiveCore exists in src/guigame.c and reuses configSet in VMC paths
assert 'guiGameResolveEffectiveCore(config_set_t *configSet, item_list_t *support, int id)' in src_gui, \
    "guiGameResolveEffectiveCore must accept configSet to prevent repeated allocations"
assert 'coreLoader = guiGameResolveEffectiveCore(configSet, support, id);' in src_gui, \
    "guiGameResolveEffectiveCore must update coreLoader in VMC paths using existing configSet"

# 3. Test production bdmNeutrinoFragBudgetOk extracted directly from src/bdmsupport.c
start = src_bdm.index('static int bdmNeutrinoFragBudgetOk(')
end = src_bdm.index('\n}\n', start) + 3
production_fn = src_bdm[start:end]
language_base = (root / 'lng_tmpl/_base.yml').read_text(encoding='utf-8')
budget_message = json.loads(re.search(
    r'^- label: NEUTRINO_VMC_FRAG_BUDGET_CONTINUE\n  string: (".*")$',
    language_base, re.M).group(1))

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NEUTRINO_BDM_MAX_FRAGS 64
#define NEUTRINO_VMC_SLOTS 2
#define O_RDONLY 0
#define USBMASS_IOCTL_GET_FRAGLIST 2

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
#define _STR_ERR_VMC_FRAGMENTED_CONTINUE 1
#define _STR_NEUTRINO_TOO_FRAGMENTED 2
#define _STR_NEUTRINO_TOO_FRAGMENTED_NET 3
#define _STR_NEUTRINO_VMC_FRAG_BUDGET_CONTINUE 4
#define LOG(...) ((void)0)
#define guiWarning(...) ((void)0)

static const char *_l(int id) {
    assert(id != _STR_ERR_VMC_FRAGMENTED_CONTINUE);
    if (id == _STR_NEUTRINO_VMC_FRAG_BUDGET_CONTINUE)
        return @BUDGET_MESSAGE@;
    return "Neutrino: %d/%d fragments";
}

static void *gAutoLaunchBDMGame = NULL;

static int stubIsoFrags = 0;
static int stubVmc0Frags = 0;
static int stubVmc1Frags = 0;

static int open(const char *path, int flags) {
    (void)flags;
    if (path == NULL) return -1;
    if (strcmp(path, "iso") == 0) return 10;
    if (strstr(path, "slot0") != NULL) return 20;
    if (strstr(path, "slot1") != NULL) return 21;
    return 30;
}

static int close(int fd) {
    (void)fd;
    return 0;
}

static int ps2sdk_get_iop_fd(int fd) {
    return fd;
}

static int fileXioIoctl2(int fd, int cmd, void *arg, int arglen, void *out, int outlen) {
    (void)cmd; (void)arg; (void)arglen; (void)out; (void)outlen;
    if (fd == 10) return stubIsoFrags;
    if (fd == 20) return stubVmc0Frags;
    if (fd == 21) return stubVmc1Frags;
    return 0;
}

/* Production function under test extracted from src/bdmsupport.c */
@PRODUCTION_FUNCTION@

int main(void) {
    neutrino_vmc_args_t vmc;

    // Case 1: Total <= 64 -> fits within budget
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    vmc.arg[1][0] = '\0';
    stubIsoFrags = 10;
    stubVmc0Frags = 5;
    stubVmc1Frags = 0;
    msgBoxCalled = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(vmc.arg[0][0] != '\0');
    assert(msgBoxCalled == 0);

    // Case 2: ISO <= 64 but ISO + VMC > 64 -> user accepts prompt -> drops VMC and returns 1
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    vmc.arg[1][0] = '\0';
    stubIsoFrags = 58;
    stubVmc0Frags = 8;
    stubVmc1Frags = 0;
    msgBoxCalled = 0;
    msgBoxResponse = 1;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(msgBoxCalled == 1);
    assert(vmc.arg[0][0] == '\0');
    assert(strstr(lastMsgBox, "slot0") != NULL);

    // Case 3: ISO <= 64 but ISO + VMC > 64 -> user declines prompt -> returns -1 (abort launch)
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    vmc.arg[1][0] = '\0';
    stubIsoFrags = 58;
    stubVmc0Frags = 8;
    stubVmc1Frags = 0;
    msgBoxCalled = 0;
    msgBoxResponse = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == -1);
    assert(msgBoxCalled == 1);

    // Case 4: ISO itself > 64 -> returns 0 (fatal ISO fragmentation)
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    vmc.arg[1][0] = '\0';
    stubIsoFrags = 65;
    stubVmc0Frags = 2;
    stubVmc1Frags = 0;
    msgBoxCalled = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 0);
    assert(msgBoxCalled == 0);

    // Case 5: Selective dropping - dropping slot 1 alone fits budget (ISO=40, VMC0=2, VMC1=30, total=72)
    // Slot 0 should be retained, slot 1 dropped. Only 1 prompt should appear.
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    strcpy(vmc.arg[1], "-mc1=mass0:/VMC/slot1.bin");
    stubIsoFrags = 40;
    stubVmc0Frags = 2;
    stubVmc1Frags = 30;
    msgBoxCalled = 0;
    msgBoxResponse = 1;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(msgBoxCalled == 1);
    assert(strstr(lastMsgBox, "slot1") != NULL);
    assert(vmc.arg[0][0] != '\0');
    assert(vmc.arg[1][0] == '\0');

    // Case 6: Both slots need to be dropped (ISO=60, VMC0=5, VMC1=5, total=70)
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    strcpy(vmc.arg[1], "-mc1=mass0:/VMC/slot1.bin");
    stubIsoFrags = 60;
    stubVmc0Frags = 5;
    stubVmc1Frags = 5;
    msgBoxCalled = 0;
    msgBoxResponse = 1;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(msgBoxCalled == 2);
    assert(vmc.arg[0][0] == '\0');
    assert(vmc.arg[1][0] == '\0');

    // Case 7: A contiguous VMC can overflow a full ISO budget. Explain the combined
    // limit rather than incorrectly claiming that the VMC itself is fragmented.
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    vmc.arg[1][0] = '\0';
    stubIsoFrags = 64;
    stubVmc0Frags = 1;
    stubVmc1Frags = 0;
    msgBoxCalled = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(msgBoxCalled == 1 && vmc.arg[0][0] == '\0');
    assert(strstr(lastMsgBox, "65/64") != NULL);
    assert(strstr(lastMsgBox, "Neutrino") != NULL);
    assert(strstr(lastMsgBox, "physical Memory Card in slot 1") != NULL);
    assert(strstr(lastMsgBox, "slot0") != NULL);
    assert(strstr(lastMsgBox, "is fragmented") == NULL);

    // Case 8: Multiple VMC extents are valid when the combined table fits exactly.
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    stubIsoFrags = 61;
    stubVmc0Frags = 3;
    msgBoxCalled = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 1);
    assert(msgBoxCalled == 0 && vmc.arg[0][0] != '\0');

    // Mapping failures are not zero-fragment successes. Do not drop cards or
    // offer a fragmentation prompt when the layout query itself failed.
    strcpy(vmc.arg[0], "-mc0=mass0:/VMC/slot0.bin");
    strcpy(vmc.arg[1], "-mc1=mass0:/VMC/slot1.bin");
    stubIsoFrags = -5; stubVmc0Frags = 1; stubVmc1Frags = 1;
    msgBoxCalled = 0;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 0);
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 1) == 0);
    assert(msgBoxCalled == 0 && vmc.arg[0][0] && vmc.arg[1][0]);
    stubIsoFrags = 1; stubVmc0Frags = -5;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 0);
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 1) == 0);
    stubVmc0Frags = 1; stubVmc1Frags = -5;
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 0) == 0);
    assert(bdmNeutrinoFragBudgetOk("iso", &vmc, 1) == 0);
    assert(msgBoxCalled == 0 && vmc.arg[0][0] && vmc.arg[1][0]);

    return 0;
}
'''.replace('@PRODUCTION_FUNCTION@', production_fn).replace('@BUDGET_MESSAGE@', json.dumps(budget_message))

with tempfile.TemporaryDirectory() as temp_dir:
    td = Path(temp_dir)
    cfile = td / 'test_harness.c'
    exe = td / 'test_harness'
    cfile.write_text(harness, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

print("PASS: bdmNeutrinoFragBudgetOk handles VMC budget overflow gracefully without catch-22")
