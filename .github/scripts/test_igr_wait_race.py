"""Reproduce raw EE iWakeupThread losing a wake between the latch read and sleep.

The SDK documents this running-thread defect; DISABLE_PATCHED_FUNCTIONS in the
resident core selects the raw syscall wrappers. Compile the actual VBLANK handler and
worker functions, scheduling a request at precisely the vulnerable boundary.
An optional git ref permits checking that the original source is rejected.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'ee_core/src/padhook.c').read_text(encoding='utf-8')
if len(sys.argv) > 1:
    source = subprocess.check_output(['git', 'show', sys.argv[1] + ':ee_core/src/padhook.c'], cwd=root, text=True)

def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start) + 3]

production = function('static int IGR_Intc_Handler(') + function('static void IGR_WaitForRequest(')
program = r'''
#include <stdio.h>
#include <stdint.h>
#include <setjmp.h>
typedef int s32;
typedef unsigned short u16;
#define DPRINTF(...) ((void)0)
#define TH_SELF 0
static struct { volatile unsigned char combo_type; } Pad_Data;
static int IGR_Thread_ID=7;
static int IGR_Request_Sema=3;
static int intrEnabled, stateWaiting, wakeCount, lostWakes, delivered;
static int sleeps, shutdowns, resets, suspends, spurious;
static jmp_buf blocked;
static inline int DI(void) { int old=intrEnabled; intrEnabled=0; return old; }
static inline void EI(void) { intrEnabled=1; }
static void IGR_CheckInputs(void) { Pad_Data.combo_type=0xf6; }
static int iChangeThreadPriority(int id, int priority) { return id==7 && priority==0 ? 0 : -1; }
static inline int iWakeupThread(int id) {
    if (id!=7 || !stateWaiting) { lostWakes++; return -1; }
    wakeCount++; return 0;
}
static inline int iSignalSema(int id) {
    if(id!=3) return -1;
    wakeCount=1; return 0; /* token persists even when the worker is RUNNING */
}
static int IGR_Intc_Handler(int);
static void ExitHandler(void) {}
static void deliver_vblank(void) {
    int old=intrEnabled; intrEnabled=0; delivered++;
    IGR_Intc_Handler(0);
    intrEnabled=old;
}
static void SleepThread(void) {
    sleeps++;
    if (spurious) { spurious=0; return; }
    /* Interrupt just before the actual syscall, while the worker is RUNNING. */
    if (intrEnabled && !delivered) deliver_vblank();
    stateWaiting=1;
    if (!wakeCount && !delivered) {
        /* Sleep dispatches a different game thread with its own IRQ state.
         * That thread's VBLANK wakes the now-WAITING worker. */
        int workerIntr=intrEnabled; intrEnabled=1;
        deliver_vblank(); intrEnabled=workerIntr;
    }
    if (!wakeCount) longjmp(blocked,1); /* cannot return: game suspended, wake lost */
    wakeCount--; stateWaiting=0;
}
static inline void WaitSema(int id) { (void)id; SleepThread(); }
static void IGR_StopDmaAndGs(void) { shutdowns++; }
static void ChangeThreadPriority(int id,int priority) { (void)id; (void)priority; }
static void ResetEE(int mask) { if(mask==0x7f) resets++; }
static void __attribute__((unused)) SuspendThread(int id) { (void)id; suspends++; }
static void __attribute__((unused)) iSuspendThread(int id) { (void)id; suspends++; }
@PRODUCTION@
static void reset(int intr) {
    (void)IGR_Request_Sema;
    Pad_Data.combo_type=0;
    intrEnabled=intr; stateWaiting=wakeCount=lostWakes=delivered=0;
    sleeps=shutdowns=resets=suspends=spurious=0;
}
#define CHECK(c) do { if(!(c)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c); return 1; } } while(0)
int main(void) {
    reset(1);
    if(setjmp(blocked)) { fputs("FAIL: request latched, game suspended, running-thread wake lost, worker asleep\n",stderr); return 1; }
    IGR_WaitForRequest();
    CHECK(delivered==1 && !lostWakes && sleeps==1 && intrEnabled==1);
    CHECK(Pad_Data.combo_type==0xf6);
    CHECK(shutdowns==1 && resets==1 && suspends==254);
    reset(1); Pad_Data.combo_type=0xf6; IGR_WaitForRequest();
    CHECK(sleeps==0 && delivered==0 && intrEnabled==1 && shutdowns==1);
    reset(1); spurious=1; IGR_WaitForRequest();
    CHECK(sleeps==2 && delivered==1 && !lostWakes && intrEnabled==1 && shutdowns==1);
    puts("IGR wait: persistent request across check/wait gap, prelatched and spurious signals pass");
    return 0;
}
'''.replace('@PRODUCTION@', production)

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    c = path / 'igr_wait.c'
    exe = path / 'igr_wait.exe'
    c.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)
