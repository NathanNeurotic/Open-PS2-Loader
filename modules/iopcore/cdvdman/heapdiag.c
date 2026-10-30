/*
  IOP heap record (INGAMEDIAG flavour only): see ../common/heap_diag.h.

  Only ingamediag builds compile this file. It hooks SYSMEM's AllocSysMemory and FreeSysMemory in
  the export table, as hookMODLOAD() does for MODLOAD: modules the game loads after CDVDMAN link to
  the hooks, and modules already linked keep calling SYSMEM directly. The hooks pass every call
  through unchanged and only take notes.
*/

#include "internal.h"
#include "ioplib_util.h"
#include "../common/heap_diag.h"

heap_diag_iop_t g_heap_diag __attribute__((aligned(16)));

static void *(*org_AllocSysMemory)(int mode, int size, void *ptr);
static int (*org_FreeSysMemory)(void *ptr);
static unsigned int heap_diag_seq;
static int heap_diag_module_index = -1, heap_diag_module_total = -1;

// Interrupts are off. The module list only changes when a module loads or unloads.
static void heap_diag_note_modules(void)
{
    lc_internals_t *lc = GetLoadcoreInternalData();
    ModuleInfo_t *m;
    unsigned int n = 0;
    int i;

    if (lc->module_index == heap_diag_module_index && lc->module_count == heap_diag_module_total)
        return;
    heap_diag_module_index = lc->module_index;
    heap_diag_module_total = lc->module_count;

    for (m = lc->image_info; m != NULL; m = m->next, n++) {
        heap_diag_module_t *d;

        if (n >= HEAP_DIAG_MODULES)
            continue;
        d = &g_heap_diag.modules[n];
        for (i = 0; i < 8 && m->name != NULL && m->name[i] != '\0'; i++)
            d->name[i] = m->name[i];
        for (; i < 8; i++)
            d->name[i] = '\0';
        d->text_start = m->text_start;
        d->size = m->text_size + m->data_size + m->bss_size;
    }
    g_heap_diag.module_count = n;
    for (; n < HEAP_DIAG_MODULES; n++)
        g_heap_diag.modules[n].text_start = 0;
}

static void heap_diag_note_free_memory(int allocated)
{
    unsigned int total = QueryTotalFreeMemSize();

    g_heap_diag.free_now = total;
    if (total < g_heap_diag.free_min)
        g_heap_diag.free_min = total;
    if (allocated) {
        unsigned int largest = QueryMaxFreeMemSize();

        if (largest < g_heap_diag.largest_min)
            g_heap_diag.largest_min = largest;
    }
}

static void *hook_AllocSysMemory(int mode, int size, void *ptr)
{
    unsigned int ra = (unsigned int)__builtin_return_address(0);
    heap_diag_block_t *slot;
    void *result;
    int oldstate, i;

    // Keep the allocation and its record together so a racing free cannot reorder them.
    CpuSuspendIntr(&oldstate);
    result = org_AllocSysMemory(mode, size, ptr);
    if (result == NULL) {
        slot = &g_heap_diag.failed[g_heap_diag.fail_next];
        g_heap_diag.fail_next = (g_heap_diag.fail_next + 1) % HEAP_DIAG_FAILS;
        slot->addr = (unsigned int)ptr;
        slot->size = (unsigned int)size;
        slot->ra = ra;
        slot->seq = (unsigned int)mode;
        g_heap_diag.fails++;
    } else {
        // An empty slot, else the oldest block.
        slot = &g_heap_diag.blocks[0];
        for (i = 0; i < HEAP_DIAG_BLOCKS; i++) {
            if (g_heap_diag.blocks[i].addr == 0) {
                slot = &g_heap_diag.blocks[i];
                break;
            }
            if (g_heap_diag.blocks[i].seq < slot->seq)
                slot = &g_heap_diag.blocks[i];
        }
        if (slot->addr != 0)
            g_heap_diag.evicted++;
        slot->addr = (unsigned int)result;
        slot->size = (unsigned int)size;
        slot->ra = ra;
        slot->seq = ++heap_diag_seq;
        g_heap_diag.allocs++;
    }
    heap_diag_note_free_memory(1);
    heap_diag_note_modules();
    CpuResumeIntr(oldstate);

    return result;
}

static int hook_FreeSysMemory(void *ptr)
{
    int result, oldstate, i;

    // Keep the free and its record update together so a racing allocation cannot reuse the slot first.
    CpuSuspendIntr(&oldstate);
    result = org_FreeSysMemory(ptr);
    for (i = 0; i < HEAP_DIAG_BLOCKS; i++) {
        if (result >= 0 && g_heap_diag.blocks[i].addr == (unsigned int)ptr && ptr != NULL) {
            g_heap_diag.blocks[i].addr = 0;
            g_heap_diag.blocks[i].seq = 0;
            g_heap_diag.frees++;
            break;
        }
    }
    if (result >= 0 && i == HEAP_DIAG_BLOCKS)
        g_heap_diag.unknown_frees++;
    heap_diag_note_free_memory(0);
    heap_diag_note_modules();
    CpuResumeIntr(oldstate);

    return result;
}

// A record left by the CDVDMAN of an earlier IOP session would be found too: wipe every copy but
// this one before arming it.
static void heap_diag_wipe_stale(void)
{
    // Below 0x800 is the IOP kernel's own area; nothing of ours lives there.
    volatile unsigned int *p = (volatile unsigned int *)0x800;
    volatile unsigned int *end = (volatile unsigned int *)HEAP_DIAG_IOP_RAM_SIZE;

    for (; p < end; p += 4) {
        if (p[0] == HEAP_DIAG_MAGIC && p[1] == HEAP_DIAG_CHECK && p != (volatile unsigned int *)&g_heap_diag)
            p[1] = 0;
    }
}

void heap_diag_install(void)
{
    modinfo_t info;
    int oldstate;

    heap_diag_wipe_stale();

    if (!getModInfo("sysmem\0\0", &info))
        return;

    CpuSuspendIntr(&oldstate);
    g_heap_diag.version = HEAP_DIAG_VERSION;
    g_heap_diag.self = (unsigned int)&g_heap_diag;
    g_heap_diag.free_min = 0xFFFFFFFF;
    g_heap_diag.largest_min = 0xFFFFFFFF;
    heap_diag_note_free_memory(1);
    heap_diag_note_modules();

    org_AllocSysMemory = (void *)info.exports[4];
    org_FreeSysMemory = (void *)info.exports[5];
    info.exports[4] = (void *)hook_AllocSysMemory;
    info.exports[5] = (void *)hook_FreeSysMemory;

    g_heap_diag.magic = HEAP_DIAG_MAGIC;
    g_heap_diag.check = HEAP_DIAG_CHECK;
    CpuResumeIntr(oldstate);

    // The modules already loaded (and the IOP pad hook's own import, when it is on) go through the
    // record too.
    relinkExports(&info);
}
