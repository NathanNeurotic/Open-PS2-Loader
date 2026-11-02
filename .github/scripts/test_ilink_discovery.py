"""Exercise production bus-reset discovery, retries and slot ownership.

The bus-reset thread and its helpers are compiled from both drivers against a simulated bus, clock and
kernel. A LOGIN or command still waiting for its status keeps its slot reserved across a bus reset; a
failed attempt releases its transaction context; FS attach/detach never runs under the I/O mutex.

A drive that did not attach is tried again without a bus reset (#1018): nothing in a running game
causes one, so the SDK's wait-for-the-next-reset left CDVDMAN waiting forever. A retry keeps the
slot (and the login) of its earlier attempt in that generation, backs off 1, 2, 4, then 5 s, and a
bus reset ends the wait at once. In the menu/in-game driver a lone drive is device 0 whichever slot
it lands in, because CDVDMAN and Neutrino accept the game's drive only under the menu's number.

With two drives, a slot that holds one drive's login of this generation is that drive's: the other
drive never takes it (it would skip its own LOGIN and drive the first one's command agent), and in
the menu/in-game driver the logged-in drive keeps its device number while its warm-up is retried. A
login left from a generation whose bus reset the thread has not handled yet is not reused.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = (ROOT / 'modules/ilink/IEEE1394_bd/src', ROOT / 'modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src')
SIGNATURES = (
    'static u32 sbp2RetryDelayUs(unsigned int retries)',
    'static int sbp2WaitBusReset(u32 us)',
    'static unsigned int sbp2FreeDevNr(const struct SBP2Device *dev)',  # the menu/in-game driver only
    'static void sbp2BusReset(void)',
    'static int sbp2AttachUnits(void)',
    'static void iLinkIntrCBHandlingThread(void *arg)',
)
DEFINES = ('SBP2_RETRY_FIRST_US', 'SBP2_RETRY_MAX_US', 'SBP2_RETRY_POLL_US', 'SBP2_RETRY_LIMIT')

HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "sbp2_disk.h"
#define MAX_DEVICES 5
#define WEF_AND 1
#define WEF_CLEAR 2
#define M_DEBUG(...) ((void)0)
static struct SBP2Device SBP2Devices[MAX_DEVICES];
static struct { int pending;struct SBP2Device *owner; } command;
static int sbp2_io_sema,sbp2_event_flag;
static int failures,held,scenario,generation,waits,allocations,frees,live[64];
static int nNodesNow,nodeIds[4],speedNow,attempts;
static unsigned long long simUs,resetAtUs;
static unsigned long long attemptUs[16];
static int attemptSlot[16],attemptNode[16],attemptGeneration[16],attemptLoggedIn[16];
static jmp_buf done;
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL: %s\n",msg);failures++; } } while(0)
static int WaitSema(int s) { (void)s;CHECK(!held,"discovery must not recursively acquire transport");held=1;return 0; }
static int SignalSema(int s) { (void)s;CHECK(held,"discovery releases owned transport");held=0;return 0; }
static int iLinkGetGenerationNumber(void) { return generation; }
static void topology(void) {
    speedNow=scenario==4 ? 3 : 0;
    if(scenario==5) {
        nNodesNow=generation==1 ? 2 : 1;nodeIds[0]=generation==1 ? 1 : 2;nodeIds[1]=2;
    } else if(scenario==6) {
        nNodesNow=2;nodeIds[0]=1;nodeIds[1]=2;
    } else if(scenario==7) { /* the reset renumbers the first drive and keeps the second at node 2 */
        nNodesNow=2;nodeIds[0]=generation==1 ? 1 : 3;nodeIds[1]=2;
    } else {
        nNodesNow=1;nodeIds[0]=generation==1 ? 1 : 3; /* a reset can renumber the lone drive */
    }
}
static void busReset(void) { generation++;topology(); }
/* Blocking wait: the thread's idle state. The second one ends the scenario. */
static int WaitEventFlag(int id,int bits,int op,void *out) {
    (void)id;(void)bits;(void)op;(void)out;
    CHECK(!held,"event wait cannot retain transport mutex");
    if(++waits>1) longjmp(done,1);
    busReset();
    return 0;
}
/* Retry wait: a bus reset scheduled for resetAtUs arrives at the first poll at or after it. */
static int PollEventFlag(int id,u32 bits,int op,u32 *out) {
    (void)id;(void)bits;(void)op;(void)out;
    CHECK(!held,"the retry wait cannot hold the transport mutex");
    if(resetAtUs && simUs>=resetAtUs) { resetAtUs=0;busReset();return 0; }
    return -421; /* KE_EVF_COND */
}
static int DelayThread(int us) { CHECK(!held,"the retry wait cannot hold the transport mutex");simUs+=us;return 0; }
static int iLinkGetNodeCount(void) { return nNodesNow; }
static int iLinkFindUnit(int index,int spec,int version) { (void)spec;(void)version;return index<nNodesNow ? nodeIds[index] : -1; }
static int iLinkGetLocalNodeID(void) { return 0xffc0; }
static int iLinkGetNodeMaxSpeed(int node) { (void)node;return speedNow; }
static int iLinkTrAlloc(int node,int speed) {
    (void)node;(void)speed;CHECK(held,"context allocation serialized with I/O");
    live[allocations]=1;return allocations++;
}
static void iLinkTrFree(int ctx) {
    CHECK(held && ctx>=0 && ctx<allocations && live[ctx],"context is freed exactly once under transport mutex");
    live[ctx]=0;frees++;
}
static int iLinkGetNodeTrSpeed(int ctx) { (void)ctx;return 0; }
static int sbp2StatusReady(struct SBP2Device *dev,void *orb) { (void)dev;(void)orb;return 0; }
static int sbp2CommandAvailable(void) { CHECK(held,"pending-state checks are serialized");return !command.pending; }
void scsi_disconnect(struct scsi_interface *iface) { (void)iface;CHECK(!held,"FS detach runs outside transport mutex"); }
static int initSBP2Disk(struct SBP2Device *dev) {
    CHECK(held,"CROM/config snapshot is serialized");
    dev->ManagementAgent_low=0xf0004000;dev->eui64[0]=0x00d04b00;dev->eui64[1]=dev->nodeID;return 1;
}
/* Each scenario decides how its attempts end. */
static int initConfigureSBP2Device(struct SBP2Device *dev) {
    CHECK(!held,"SCSI warm-up can submit requests without recursive transport lock");
    if(attempts<16) {
        attemptUs[attempts]=simUs;attemptSlot[attempts]=dev-SBP2Devices;attemptNode[attempts]=dev->nodeID;
        attemptGeneration[attempts]=generation;attemptLoggedIn[attempts]=dev->loggedIn;
    }
    attempts++;
    switch(scenario) {
        case 1: /* the LOGIN of generation 1 is never answered */
        case 5:
            if(generation==1 && dev->nodeID==1) { dev->managementPending=1;return -1; }
            return 0;
        case 2: /* the LOGIN is granted, the first warm-up fails */
            if(attempts==1) { dev->loggedIn=1;return -3; }
            return 0;
        case 3: /* never attaches */
            if(attempts>=6) longjmp(done,1);
            return -1;
        case 6: /* two drives, every LOGIN granted: node 1's first warm-up fails */
            dev->loggedIn=1;
            return dev->nodeID==1 && attempts==1 ? -3 : 0;
        case 7: /* two drives: a bus reset ends node 1's first warm-up, after its LOGIN was granted; the
                   thread has not handled that reset when it moves on to the next node */
            dev->loggedIn=1;
            if(attempts==1) { generation++;topology(); }
            return 0;
    }
    return 0;
}
@FUNCTIONS@
static void run(int which,unsigned long long reset_at) {
    memset(SBP2Devices,0,sizeof(SBP2Devices));memset(live,0,sizeof(live));memset(&command,0,sizeof(command));
    memset(attemptUs,0,sizeof(attemptUs));
    for(int i=0;i<MAX_DEVICES;i++) { SBP2Devices[i].trContext=-1;SBP2Devices[i].scsi.priv=&SBP2Devices[i]; }
    scenario=which;generation=waits=held=allocations=frees=attempts=0;simUs=0;resetAtUs=reset_at;
    if(setjmp(done)==0) iLinkIntrCBHandlingThread(NULL);
    CHECK(!held,"all paths release the transport mutex");
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);

    /* A lone drive whose LOGIN is never answered; a bus reset arrives 0.5 s into the first retry wait. */
    run(1,500000);
    CHECK(attempts==2 && attemptSlot[0]==0 && attemptSlot[1]==1 && attemptGeneration[1]==2,
          "a slot whose LOGIN never got its status stays reserved across the bus reset");
    CHECK(attemptUs[1]==500000,"a bus reset ends the retry wait at once");
    CHECK(SBP2Devices[0].managementPending && SBP2Devices[0].nodeID==1 && SBP2Devices[0].trContext==-1,
          "the still-live LOGIN keeps its storage");
    CHECK(SBP2Devices[1].IsConnected && SBP2Devices[1].nodeID==3 && SBP2Devices[1].generation==2,
          "the drive attaches in the next free slot in the new generation");
#ifdef HAS_DEVNR
    CHECK(SBP2Devices[1].scsi.devNr==0,"a lone drive is device 0 whichever slot it lands in, as the game expects");
#endif
    CHECK(allocations==2 && frees==1,"the failed attempt releases its context");

    /* The LOGIN is granted and the warm-up fails once; no bus reset ever comes. */
    run(2,0);
    CHECK(attempts==2 && attemptSlot[1]==0 && attemptGeneration[1]==1,
          "a retry without a bus reset keeps the slot of its earlier attempt");
    CHECK(attemptLoggedIn[1],"a retry keeps the login this generation already granted");
    CHECK(attemptUs[1]==1000000,"the first retry comes 1 s after the failure");
    CHECK(SBP2Devices[0].IsConnected && waits==2 && generation==1,"the drive attaches without a bus reset");
#ifdef HAS_DEVNR
    CHECK(SBP2Devices[0].scsi.devNr==0,"the retried drive is device 0");
#endif
    CHECK(allocations==2 && frees==1,"each failed attempt releases its context");

    /* A drive that never attaches: the thread keeps trying, backing off to every 5 s. */
    run(3,0);
    static const unsigned long long gaps[]={1000000,2000000,4000000,5000000,5000000};
    int backoff=attempts==6;
    for(int i=0;i<5;i++)
        backoff=backoff && attemptUs[i+1]-attemptUs[i]==gaps[i] && attemptSlot[i+1]==0;
    CHECK(backoff,"retries back off 1, 2, 4, then 5 s and keep the drive's slot");
    CHECK(waits==1,"retries do not wait for a bus reset");

    /* A speed this driver cannot use is permanent: no context, no attempt, no retry. */
    run(4,0);
    CHECK(!allocations && !attempts && simUs==0,"an unusable node is neither configured nor retried");

    /* Two drives: node 1's LOGIN is never answered; node 2 attaches. A reset comes during the
       second retry wait and node 1 leaves the bus. */
    run(5,2500000);
    CHECK(attempts==4 && attemptNode[2]==1 && attemptSlot[2]==0 && attemptGeneration[2]==1,
          "only the drive that did not attach is retried, in its own slot");
    CHECK(attemptNode[3]==2 && attemptSlot[3]==1 && attemptGeneration[3]==2,
          "after the reset the attached drive comes back; the reserved slot is skipped");
    CHECK(SBP2Devices[0].managementPending && SBP2Devices[0].nodeID==1 && SBP2Devices[0].trContext==-1,
          "still-live LOGIN retains its original slot across discovery and reset");
    CHECK(SBP2Devices[1].IsConnected && SBP2Devices[1].nodeID==2 && SBP2Devices[1].generation==2,
          "only successfully configured current-generation node is connected");
#ifdef HAS_DEVNR
    CHECK(SBP2Devices[1].scsi.devNr==0,"the only attached drive is device 0");
#endif
    CHECK(allocations==4 && frees==3,"failed setup and later bus reset each release their old context");

    /* Two drives: node 1's LOGIN is granted and its first warm-up fails; node 2 comes next in the same pass. */
    run(6,0);
    CHECK(attempts==3 && attemptNode[1]==2 && attemptSlot[1]==1 && !attemptLoggedIn[1],
          "a second drive does not take the slot that holds the first drive's login; it asks for its own");
    CHECK(attemptNode[2]==1 && attemptSlot[2]==0 && attemptLoggedIn[2] && attemptGeneration[2]==1,
          "the first drive's retry reuses its own login in its own slot");
    CHECK(SBP2Devices[0].IsConnected && SBP2Devices[0].nodeID==1 && SBP2Devices[1].IsConnected && SBP2Devices[1].nodeID==2,
          "both drives attach without a bus reset");
#ifdef HAS_DEVNR
    CHECK(SBP2Devices[0].scsi.devNr==0 && SBP2Devices[1].scsi.devNr==1,
          "the first drive keeps device 0 while its warm-up is retried");
#endif
    CHECK(allocations==3 && frees==1,"the failed warm-up releases its context");

    /* Two drives: a bus reset the thread has not handled yet ends node 1's login during its warm-up. */
    run(7,0);
    CHECK(attempts==3 && attemptNode[1]==2 && attemptGeneration[1]==2 && attemptSlot[1]==0,
          "the next drive may take the slot of a login from an earlier generation");
    CHECK(!attemptLoggedIn[1],"a login from an earlier generation is not reused: the drive asks for its own");
    CHECK(SBP2Devices[0].IsConnected && SBP2Devices[0].nodeID==2 && SBP2Devices[1].IsConnected && SBP2Devices[1].nodeID==3,
          "both drives attach in the new generation");
    CHECK(allocations==3 && frees==1,"the attempt the reset ended releases its context");
    return failures ? 1 : 0;
}
"""


def function(source, signature):
    start = source.index(signature + '\n{')
    return source[start:source.index('\n}', start) + 2]


def define(source, name):
    for line in source.splitlines():
        if line.startswith('#define %s ' % name):
            return line
    raise ValueError('%s not defined' % name)


def run(driver):
    source = (driver / 'sbp2_driver.c').read_text(encoding='utf-8')
    has_devnr = 'static unsigned int sbp2FreeDevNr(' in source
    parts = [define(source, name) for name in DEFINES]
    parts += [function(source, s) for s in SIGNATURES if has_devnr or 'sbp2FreeDevNr' not in s]
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        cfile = folder / 'discovery.c'
        exe = folder / ('discovery.exe' if sys.platform == 'win32' else 'discovery')
        (folder / 'tamtypes.h').write_text('#include <stdint.h>\ntypedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;\n')
        cfile.write_text(HARNESS.replace('@FUNCTIONS@', '\n\n'.join(parts)), encoding='utf-8')
        subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-clobbered'] +
                       (['-DHAS_DEVNR'] if has_devnr else []) +
                       ['-I', str(folder), '-I', str(driver / 'include'), str(cfile), '-o', str(exe)], check=True, timeout=60)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        print(str(driver) + ':')
        if result.returncode == 0:
            print(result.stdout.strip() or 'PASS: reset ownership, retries without a reset, back-off and pending-slot retention')
        else:
            print(result.stdout.strip() or 'FAIL: harness exited %d' % result.returncode)
            if result.stderr:
                print(result.stderr.strip())
        return result.returncode == 0


if __name__ == '__main__':
    results = [run(p) for p in DRIVERS]
    sys.exit(0 if all(results) else 1)
