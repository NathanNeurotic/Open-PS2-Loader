"""Run production IGR handoff against a cooperative EE scheduling model.

A newly ready thread does not preempt a running thread at the same priority.
Exercise both a priority-0 game and another priority-0 ready thread: raising
the IGR worker to 0 alone cannot give it the CPU. Also run the actual worker
across its semaphore wait and the interrupt-before-wait boundary. Hardware
reset/input operations are stubs; request delivery and handoff are production
functions. An optional git ref demonstrates that the previous source fails.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'ee_core/src/padhook.c').read_text(encoding='utf-8')
if len(sys.argv) > 1:
    source = subprocess.check_output(
        ['git', 'show', sys.argv[1] + ':ee_core/src/padhook.c'], cwd=ROOT, text=True)


def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start) + 3]


production = function('static int IGR_Intc_Handler(') + function('static void IGR_WaitForRequest(')
program = r'''
#include <stdint.h>
#include <stdio.h>
#include <ucontext.h>

typedef int s32;
typedef unsigned short u16;
#define TH_SELF 0
#define DPRINTF(...) ((void)0)

enum { DORMANT, READY, RUNNING, WAITING, SUSPENDED };
struct thread { int state, priority, order; } threads[256];
static struct { volatile unsigned char combo_type; } Pad_Data;
static int IGR_Thread_ID = 7, IGR_Request_Sema = 3;
static int current, semaCount, semaGranted, waits, shutdowns, resets, completed;
static int irqAtWait, irqActive, intrEnabled = 1, interruptSuspends, threadSuspends;
static ucontext_t schedulerContext, workerContext;
static unsigned char workerStack[32768];

static int IGR_Intc_Handler(int);
static void ExitHandler(void) {}
static void deliverVblank(void)
{
    int old = intrEnabled;
    intrEnabled = 0;
    irqActive = 1;
    IGR_Intc_Handler(0);
    irqActive = 0;
    intrEnabled = old;
}
static int DI(void) { int old = intrEnabled; intrEnabled = 0; return old; }
static void EI(void) { intrEnabled = 1; }
static void IGR_CheckInputs(void) { Pad_Data.combo_type = 0xf6; }
static int iChangeThreadPriority(int id, int priority)
{
    threads[id].priority = priority;
    return 0;
}
static int iSuspendThread(int id)
{
    if (id <= 0 || id >= 256 || threads[id].state == DORMANT)
        return -1;
    threads[id].state = SUSPENDED;
    interruptSuspends++;
    return 0;
}
static int iSignalSema(int id)
{
    if (id != IGR_Request_Sema)
        return -1;
    if (threads[IGR_Thread_ID].state == WAITING) {
        threads[IGR_Thread_ID].state = READY;
        semaGranted = 1;
    } else {
        semaCount = 1;
    }
    return 0;
}
static int WaitSema(int id)
{
    if (id != IGR_Request_Sema || irqActive)
        return -1;
    waits++;
    if (irqAtWait) {
        irqAtWait = 0;
        deliverVblank(); /* worker is RUNNING, before the blocking syscall */
    }
    if (semaCount) {
        semaCount--;
        return 0;
    }
    threads[IGR_Thread_ID].state = WAITING;
    current = -1;
    swapcontext(&workerContext, &schedulerContext);
    if (!semaGranted) {
        fputs("FAIL: worker resumed without semaphore grant\n", stderr);
        return -1;
    }
    semaGranted = 0;
    return 0;
}
static void ChangeThreadPriority(int id, int priority)
{
    threads[id == TH_SELF ? current : id].priority = priority;
}
static void IGR_StopDmaAndGs(void) { shutdowns++; }
static void ResetEE(int mask) { if (mask == 0x7f) resets++; }
static void SuspendThread(int id)
{
    if (id > 0 && id < 256 && threads[id].state != DORMANT) {
        threads[id].state = SUSPENDED;
        threadSuspends++;
    }
}
@PRODUCTION@

static void workerEntry(void)
{
    IGR_WaitForRequest();
    completed++;
    threads[IGR_Thread_ID].state = DORMANT;
    current = -1;
}
static void reset(void)
{
    for (int i = 0; i < 256; i++)
        threads[i] = (struct thread){DORMANT, 127, i};
    threads[IGR_Thread_ID] = (struct thread){READY, 127, 7};
    Pad_Data.combo_type = 0;
    current = -1;
    semaCount = semaGranted = waits = shutdowns = resets = completed = 0;
    irqAtWait = irqActive = interruptSuspends = threadSuspends = 0;
    intrEnabled = 1;
    getcontext(&workerContext);
    workerContext.uc_stack.ss_sp = workerStack;
    workerContext.uc_stack.ss_size = sizeof(workerStack);
    workerContext.uc_link = &schedulerContext;
    makecontext(&workerContext, workerEntry, 0);
}
static void runWorker(void)
{
    current = IGR_Thread_ID;
    threads[current].state = RUNNING;
    swapcontext(&schedulerContext, &workerContext);
}
static void occupyPriorityZero(void)
{
    threads[3] = (struct thread){RUNNING, 0, 1};
    threads[5] = (struct thread){READY, 0, 2};
    current = 3;
}
static void dispatchAfterInterrupt(void)
{
    int best = -1;
    for (int i = 1; i < 256; i++) {
        if (threads[i].state == READY &&
            (best < 0 || threads[i].priority < threads[best].priority ||
             (threads[i].priority == threads[best].priority && threads[i].order < threads[best].order)))
            best = i;
    }
    /* EE scheduling has no automatic equal-priority timeslice. A game that
     * remains RUNNING keeps the CPU unless a strictly higher priority wakes. */
    if (current >= 0 && threads[current].state == RUNNING &&
        (best < 0 || threads[current].priority <= threads[best].priority))
        return;
    current = best;
    if (best == IGR_Thread_ID)
        runWorker();
    else if (best >= 0)
        threads[best].state = RUNNING; /* this game thread does not yield */
}
static int check(const char *name, int condition)
{
    printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
    return !condition;
}
int main(void)
{
    int failures = 0;

    reset();
    occupyPriorityZero();
    deliverVblank();
    dispatchAfterInterrupt();
    failures += check("priority-0 game yields to worker before its first wait",
                      completed == 1 && shutdowns == 1 && resets == 1 && waits == 0 &&
                      threads[3].state == SUSPENDED && threads[5].state == SUSPENDED && semaCount == 1);

    reset();
    runWorker(); /* execute the production wait, retaining its real stack */
    failures += check("worker blocks without an IGR request", waits == 1 && completed == 0 &&
                      threads[IGR_Thread_ID].state == WAITING && shutdowns == 0);
    occupyPriorityZero();
    deliverVblank();
    dispatchAfterInterrupt();
    failures += check("waiting worker preempts current and queued priority-0 game threads",
                      completed == 1 && shutdowns == 1 && resets == 1 && waits == 1 &&
                      threads[3].state == SUSPENDED && threads[5].state == SUSPENDED &&
                      semaCount == 0 && semaGranted == 0);

    reset();
    threads[3] = (struct thread){READY, 127, 1};
    threads[5] = (struct thread){READY, 127, 2};
    irqAtWait = 1;
    runWorker();
    failures += check("request immediately before wait retains its semaphore notification",
                      completed == 1 && shutdowns == 1 && resets == 1 && waits == 1 &&
                      semaCount == 0 && semaGranted == 0 && intrEnabled == 1);
    return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory(prefix='igr-priority-') as directory:
    temp = Path(directory)
    c_file, executable = temp / 'handoff.c', temp / 'handoff'
    c_file.write_text(program.replace('@PRODUCTION@', production), encoding='utf-8')
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function',
                    '-Wno-unused-variable', str(c_file), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
