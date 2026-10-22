"""Exercise the real SBP-2 completion paths in both shipped i.LINK drivers.

A successful LOGIN leaves statusFIFO populated. The following dummy ORB must
not consume that stale completion or free its buffer before the target replies.
Also check failed dummy completions and ambiguous command-pointer publication.
The simulated target sends its own status after a configurable delay; a host
guard escapes nonterminating waits without adding a timeout to production code.
"""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DRIVERS = (
    Path('modules/ilink/IEEE1394_bd/src'),
    Path('modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src'),
)


def function(source, signature):
    start = source.index(signature + '\n{')
    return source[start:source.index('\n}', start) + 2]


HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sbp2_disk.h"
#define M_DEBUG(...) ((void)0)
#define M_PRINTF(...) ((void)0)
#define BSWAP32(v) __builtin_bswap32(v)
static volatile union {
    struct sbp2_status status;
    unsigned char buffer[32];
} statusFIFO;
static unsigned char writeStorage[XFER_BLOCK_SIZE];
static unsigned char *writeBuffer = writeStorage;
static unsigned long long now_us, due_us, reply_delay_us;
static unsigned int reply_status;
static int submitted, notified, freed_early, submit_failure, polls, failures;
static int accepted_before_error, reset_failure, suppress_reply;
static jmp_buf guard;
static void *live_orb;

static void *tracked_alloc(size_t bytes)
{
    live_orb = calloc(1, bytes);
    assert(live_orb);
    return live_orb;
}
static void tracked_free(void *buffer)
{
    if (submitted && !notified)
        freed_early++;
    assert(buffer == live_orb);
    free(buffer);
    live_orb = NULL;
}
#define malloc tracked_alloc
#define free tracked_free
static void DelayThread(unsigned int usec)
{
    now_us += usec;
    polls++;
    if (submitted && !notified && !suppress_reply && now_us >= due_us) {
        statusFIFO.status.status = reply_status;
        notified = 1;
    }
    if (now_us > 2000000)
        longjmp(guard, 1);
}
static int iLinkTrWrite(int context, unsigned long high, unsigned long low,
                        void *buffer, unsigned int count)
{
    (void)context; (void)high; (void)low; (void)buffer;
    if (count == 8) {
        if (submit_failure) {
            if (accepted_before_error && !submitted) {
                submitted = 1;
                due_us = now_us + reply_delay_us;
            }
            return -1024; /* split timeout does not prove that the pointer was rejected */
        }
        submitted = 1;
        due_us = now_us + reply_delay_us;
        if (reply_delay_us == 0) {
            statusFIFO.status.status = reply_status;
            notified = 1;
        }
    }
    return count == 4 && reset_failure ? -1024 : 0;
}
static int ieee1394_GetFetchAgentState(struct SBP2Device *dev) { (void)dev; return 0; }
@FUNCTIONS@
#undef malloc
#undef free

#define CHECK(condition, message) do { \
    if (!(condition)) { printf("FAIL: %s\n", message); failures++; } \
} while (0)

static void reset_case(unsigned int stale, unsigned int reply, unsigned int delay)
{
    if (live_orb) {
        free(live_orb);
        live_orb = NULL;
    }
    memset((void *)&statusFIFO, 0, sizeof(statusFIFO));
    statusFIFO.status.status = stale;
    now_us = due_us = 0;
    reply_delay_us = delay;
    reply_status = reply;
    submitted = notified = freed_early = submit_failure = polls = 0;
    accepted_before_error = reset_failure = suppress_reply = 0;
}

int main(void)
{
    const unsigned int good = (1u << 30) | (1u << 24);
    const unsigned int dummy_done = good | (0x0bu << 16);
    const unsigned int bad = good | (2u << 16);
    struct SBP2Device dev = {0};
    dev.ORB_size = sizeof(struct management_ORB) / 4;
    dev.scsi.priv = &dev;
    int result;

    /* LOGIN already succeeded; the dummy request has not completed yet. */
    static const unsigned int delays[] = {50, 500, 20000, 250000};
    for (unsigned int i = 0; i < sizeof(delays) / sizeof(delays[0]); i++) {
        reset_case(good, dummy_done, delays[i]);
        result = ieee1394_InitializeFetchAgent(&dev);
        CHECK(result >= 0, "successful dummy ORB initializes the fetch agent");
        CHECK(notified && now_us >= delays[i], "wait for dummy completion instead of consuming LOGIN status");
        CHECK(!freed_early, "keep the dummy ORB alive until its target completion");
    }

    /* Real completions can arrive before the pointer write returns. */
    reset_case(good, dummy_done, 0);
    result = ieee1394_InitializeFetchAgent(&dev);
    CHECK(result >= 0 && notified && !freed_early,
          "preserve a dummy completion delivered inside the pointer write");

    reset_case(good, bad, 750);
    result = ieee1394_InitializeFetchAgent(&dev);
    CHECK(result < 0, "a stale successful LOGIN cannot conceal dummy-ORB failure");
    CHECK(notified && !freed_early, "wait for the failing dummy completion before freeing");

    reset_case(0, bad, 500);
    result = ieee1394_InitializeFetchAgent(&dev);
    CHECK(result < 0, "propagate a failed dummy completion even with initially empty status");

    /* Preserve the old wait until transport failure recovery can prove quiescence. */
    reset_case(good, good, 500);
    submit_failure = 1;
    unsigned char command[12] = {0x28};
    if (setjmp(guard) == 0) {
        result = sbp2_queue_cmd(&dev.scsi, command, sizeof(command), NULL, 0, 0);
        CHECK(0, "publication failure alone cannot authorize releasing command storage");
    } else {
        CHECK(!submitted, "the host guard observes the known no-completion wait");
    }

    /* The bridge accepted the pointer, but every acknowledgment and reset fails. */
    reset_case(0, good, 1200000);
    submit_failure = accepted_before_error = reset_failure = 1;
    result = sbp2_queue_cmd(&dev.scsi, command, sizeof(command), NULL, 0, 0);
    CHECK(notified && now_us >= 1200000,
          "do not release a live command after an ambiguous publication error");
    CHECK(result == 0, "a lost pointer acknowledgment does not discard its later completion");

    /* A missing dummy completion must retain its request, even after the host guard. */
    reset_case(good, dummy_done, 500);
    suppress_reply = 1;
    if (setjmp(guard) == 0) {
        result = ieee1394_InitializeFetchAgent(&dev);
        CHECK(0, "stale LOGIN cannot authorize release when the dummy completion is missing");
    } else {
        CHECK(live_orb != NULL && !freed_early,
              "keep an accepted dummy request alive while its completion is missing");
    }

    reset_case(good, good, 1000);
    result = sbp2_queue_cmd(&dev.scsi, command, sizeof(command), NULL, 0, 0);
    CHECK(result == 0 && notified && now_us >= 1000,
          "a normal command waits for its own delayed completion");

    reset_case(good, bad, 250);
    result = sbp2_queue_cmd(&dev.scsi, command, sizeof(command), NULL, 0, 0);
    CHECK(result < 0 && notified, "propagate a command completion error");

    reset_case(0, 0, 0);
    return failures ? 1 : 0;
}
'''


def run(driver):
    source = (driver / 'sbp2_driver.c').read_text(encoding='utf-8')
    signatures = (
        'static void ieee1394_ResetFetchAgent(struct SBP2Device *dev)',
        'static int ieee1394_InitializeFetchAgent(struct SBP2Device *dev)',
        'int ieee1394_SendCommandBlockORB(struct SBP2Device *dev, struct CommandDescriptorBlock *firstCDB)',
        'static int sbp2_queue_cmd(struct scsi_interface *scsi, const unsigned char *cmd, unsigned int cmd_len, unsigned char *data, unsigned int data_len, unsigned int data_wr)',
        'static int ProcessStatus(void)',
        'int ieee1394_Sync(void)',
    )
    functions = '\n\n'.join(function(source, signature) for signature in signatures)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / 'tamtypes.h').write_text(
            '#include <stdint.h>\ntypedef uint8_t u8; typedef uint16_t u16; '
            'typedef uint32_t u32; typedef uint64_t u64;\n', encoding='utf-8')
        cfile = folder / 'completion.c'
        binary = folder / ('completion.exe' if sys.platform == 'win32' else 'completion')
        cfile.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        subprocess.run([
            'gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
            '-Wno-pointer-to-int-cast', '-I', str(folder), '-I', str(driver / 'include'),
            str(cfile), '-o', str(binary),
        ], check=True, timeout=60)
        completed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        print(str(driver) + ':')
        print(completed.stdout.strip() or 'PASS: stale, immediate, delayed and failed SBP-2 completions')
        return completed.returncode == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='Alternate checkout to test, e.g. the unpatched baseline')
    args = parser.parse_args()
    results = [run(args.source_root.resolve() / driver) for driver in DRIVERS]
    sys.exit(0 if all(results) else 1)
