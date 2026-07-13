/*
  Copyright 2009, Ifcaro, Volca
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#include "include/opl.h"
#include "include/pad.h"
#include "include/diag.h"
#include "include/ioman.h"
#include <delaythread.h>
#include <libpad.h>
#include <timer.h>
#include <time.h>

#ifdef PADEMU
#include <libds34bt.h>
#include <libds34usb.h>
#endif

#define MAX_PADS 4

// Cpu ticks per one milisecond
#define CLOCKS_PER_MILISEC 147456

// 200 ms per repeat
#define DEFAULT_PAD_DELAY 200

struct pad_data_t
{
    int port, slot;
    int state;
    u32 paddata;
    u32 oldpaddata;
    struct padButtonStatus buttons;

    // pad_dma_buf is provided by the user, one buf for each pad
    // contains the pad's current state
    char padBuf[256] __attribute__((aligned(64)));

    char actAlign[6];
    int actuators;
    int analogCapable; // -1 unknown/not ready, 0 digital-only, 1 DualShock-capable
    int analogRetryDelay;
};

// Pad commands are asynchronous. Keep every wait bounded so a transient SIO2/pad error cannot hang the
// GUI thread, then retry DualShock recovery periodically for as long as the controller remains digital.
#define PAD_WAIT_POLLS         25
#define PAD_WAIT_POLL_US       1000
#define PAD_ANALOG_RETRY_DELAY 60
// A padSetMainMode round-trip can NEVER finish under freepad's own minimum latency: the IOP main
// thread dispatches the task on the next vblank, SetMainModeThread needs three vblank-gated SIO2
// transfers, and the request only flips COMPLETE after the next good ReadData -- >= 5 vblanks,
// ~83-100 ms. The generic 25 ms budget above therefore ALWAYS timed out on this leg, so analog
// arming worked only when the IOP happened to finish in the background and the pressure/rumble
// setup below it was unreachable. Give request-completion waits a budget above the happy path.
#define PAD_REQ_WAIT_POLLS     150

#define PAD_INIT_RETRY       -1
#define PAD_INIT_UNSUPPORTED 0
#define PAD_INIT_OK          1

/// current time in miliseconds (last update time)
static u32 curtime = 0;
static u32 time_since_last = 0;

static unsigned short pad_count;
static struct pad_data_t pad_data[MAX_PADS];

// gathered pad data
static u32 paddata;
static u32 oldpaddata;

static int delaycnt[16];
static int paddelay[16];

// KEY_ to PAD_ conversion table
static const int keyToPad[17] = {
    -1,
    PAD_LEFT,
    PAD_DOWN,
    PAD_RIGHT,
    PAD_UP,
    PAD_START,
    PAD_R3,
    PAD_L3,
    PAD_SELECT,
    PAD_SQUARE,
    PAD_CROSS,
    PAD_CIRCLE,
    PAD_TRIANGLE,
    PAD_R1,
    PAD_L1,
    PAD_R2,
    PAD_L2};

static int isPadReadyState(int state)
{
    return (state == PAD_STATE_STABLE) || (state == PAD_STATE_FINDCTP1);
}

/*
 * waitPadReady()
 */
static int waitPadReady(struct pad_data_t *pad)
{
    int state = PAD_STATE_DISCONN;
    int polls;

    for (polls = 0; polls < PAD_WAIT_POLLS; polls++) {
        state = padGetState(pad->port, pad->slot);
        if (isPadReadyState(state) || (state == PAD_STATE_DISCONN))
            return state;
        DelayThread(PAD_WAIT_POLL_US);
    }

    LOG("PAD pad %d,%d ready wait timed out in state %d\n", pad->port, pad->slot, state);

    return state;
}

static int waitPadRequestComplete(struct pad_data_t *pad)
{
    int reqState = PAD_RSTAT_BUSY;
    int polls;

    for (polls = 0; polls < PAD_REQ_WAIT_POLLS; polls++) {
        reqState = padGetReqState(pad->port, pad->slot);
        if (reqState != PAD_RSTAT_BUSY)
            return reqState == PAD_RSTAT_COMPLETE;
        DelayThread(PAD_WAIT_POLL_US);
    }

    gDiag.padReqTimeout++; // PAD HUD TO: request never left BUSY within the budget
    LOG("PAD pad %d,%d request timed out\n", pad->port, pad->slot);
    return 0;
}

static int initializePad(struct pad_data_t *pad)
{
    int tmp;
    int modes;
    int i;
    int state;

    LOG("PAD initializing pad %d,%d\n", pad->port, pad->slot);

    // is there any device connected to that port?
    state = waitPadReady(pad);
    if (state == PAD_STATE_DISCONN) {
        LOG("PAD pad %d,%d not connected.\n", pad->port, pad->slot);
        return PAD_INIT_RETRY;
    }
    if (!isPadReadyState(state))
        return PAD_INIT_RETRY;

    // How many different modes can this device operate in?
    // i.e. get # entrys in the modetable
    modes = padInfoMode(pad->port, pad->slot, PAD_MODETABLE, -1);
    LOG("PAD The device has %d modes: ", modes);

    if (modes > 0) {
        LOG("( ");

        for (i = 0; i < modes; i++) {
            tmp = padInfoMode(pad->port, pad->slot, PAD_MODETABLE, i);
            LOG("%d ", tmp);
        }

        LOG(")\n");
    }

    tmp = padInfoMode(pad->port, pad->slot, PAD_MODECURID, 0);
    LOG("PAD It is currently using mode %d\n", tmp);

    // A not-yet-ready DualShock also reports an empty mode table, so keep it retryable. Once a
    // non-empty table proves that DualShock mode is absent, mark the controller unsupported.
    if (modes <= 0) {
        // Snapshot BEFORE bailing so a PERSISTENT empty-table failure shows md:0 on the PAD HUD
        // instead of a stale last-good snapshot masking exactly the state under investigation.
        gDiag.padModes = modes;
        gDiag.padMode0 = -1;
        gDiag.padMode1 = -1;
        LOG("PAD mode table is not ready (or controller is digital-only)\n");
        return PAD_INIT_RETRY;
    }

    // Verify that the controller has a DUAL SHOCK mode. CRITICAL: freepad's query threads have a
    // 10-attempt budget per stage, and under sustained SIO2 contention (MMCE/MX4SIO boot traffic)
    // they can publish numModes > 0 while the mode TABLE entries were never written (BSS zero).
    // Legal CTP mode types are 2..7 and freepad only writes an entry on a validated controller
    // response, so a 0/invalid entry PROVES the table is half-built -- that must stay RETRYABLE.
    // The old code latched analogCapable=0 ("digital-only") off exactly that half-built table,
    // permanently disarming the self-heal (its gate is analogCapable != 0) until a physical
    // unplug/replug reset it via the DISCONN edge: the intermittent dead-analog bug (Nathan +
    // FifthFox + 2 testers). Only a FULLY-published table lacking DUALSHOCK may latch digital-only.
    int sawInvalid = 0;
    int hasDualshock = 0;
    for (i = 0; i < modes; i++) {
        tmp = padInfoMode(pad->port, pad->slot, PAD_MODETABLE, i);
        if (tmp == PAD_TYPE_DUALSHOCK)
            hasDualshock = 1;
        else if (tmp == 0)
            sawInvalid = 1; // freepad writes entries only from validated responses -> 0 = unwritten slot
    }
    gDiag.padModes = modes; // PAD HUD md/t0/t1: last mode-table snapshot
    gDiag.padMode0 = (modes > 0) ? padInfoMode(pad->port, pad->slot, PAD_MODETABLE, 0) : -1;
    gDiag.padMode1 = (modes > 1) ? padInfoMode(pad->port, pad->slot, PAD_MODETABLE, 1) : -1;

    if (!hasDualshock) {
        if (sawInvalid) {
            LOG("PAD mode table half-built (contention?) -- retrying, NOT latching digital-only\n");
            return PAD_INIT_RETRY; // analogCapable stays -1/previous: the self-heal keeps trying
        }
        LOG("PAD This is no Dual Shock controller\n");
        gDiag.padUnsupported++; // PAD HUD UN: genuine fully-published digital-only verdicts
        pad->analogCapable = 0;
        gDiag.padAnalogCapable = 0; // PAD HUD AC
        return PAD_INIT_UNSUPPORTED;
    }
    pad->analogCapable = 1;
    gDiag.padAnalogCapable = 1; // PAD HUD AC

    // If ExId != 0x0 => This controller has actuator engines
    // This check should always pass if the Dual Shock test above passed
    tmp = padInfoMode(pad->port, pad->slot, PAD_MODECUREXID, 0);
    if (tmp == 0) {
        LOG("PAD This is no Dual Shock controller??\n");
        return PAD_INIT_RETRY;
    }

    LOG("PAD Enabling dual shock functions\n");

    // When using MMODE_LOCK, user cant change mode with Select button
    tmp = padSetMainMode(pad->port, pad->slot, PAD_MMODE_DUALSHOCK, PAD_MMODE_LOCK);
    if (tmp != 1 || !waitPadRequestComplete(pad)) {
        LOG("PAD padSetMainMode failed: accepted=%d req=%d\n", tmp, padGetReqState(pad->port, pad->slot));
        return PAD_INIT_RETRY;
    }
    gDiag.padSetMainModeOk++; // PAD HUD SM: padSetMainMode accepted AND observed complete

    if (!isPadReadyState(waitPadReady(pad)))
        return PAD_INIT_RETRY;
    tmp = padInfoPressMode(pad->port, pad->slot);
    LOG("PAD infoPressMode: %d\n", tmp);

    if (!isPadReadyState(waitPadReady(pad)))
        return PAD_INIT_RETRY;
    tmp = padEnterPressMode(pad->port, pad->slot);
    LOG("PAD enterPressMode: %d\n", tmp);
    if (tmp == 1 && !waitPadRequestComplete(pad))
        LOG("PAD enterPressMode request failed\n");

    if (!isPadReadyState(waitPadReady(pad)))
        return PAD_INIT_OK; // analog mode is restored; pressure/rumble setup can wait for reconnect
    pad->actuators = padInfoAct(pad->port, pad->slot, -1, 0);
    LOG("PAD # of actuators: %d\n", pad->actuators);

    if (pad->actuators != 0) {
        pad->actAlign[0] = 0; // Enable small engine
        pad->actAlign[1] = 1; // Enable big engine
        pad->actAlign[2] = 0xff;
        pad->actAlign[3] = 0xff;
        pad->actAlign[4] = 0xff;
        pad->actAlign[5] = 0xff;

        if (!isPadReadyState(waitPadReady(pad)))
            return PAD_INIT_OK;
        tmp = padSetActAlign(pad->port, pad->slot, pad->actAlign);
        LOG("PAD padSetActAlign: %d\n", tmp);
        if (tmp == 1 && !waitPadRequestComplete(pad))
            LOG("PAD padSetActAlign request failed\n");
    } else {
        LOG("PAD Did not find any actuators.\n");
    }

    waitPadReady(pad);
    return PAD_INIT_OK;
}

static void updatePadState(struct pad_data_t *pad, int state)
{ // To simplify processing, monitor only Disconnected, FindCTP1 & Stable states.
    if ((state == PAD_STATE_DISCONN) || (state == PAD_STATE_STABLE) || (state == PAD_STATE_FINDCTP1))
        pad->state = state;
}

static u32 readLeftJoy(struct pad_data_t *pad, u32 pdata)
{
    u32 padData = pdata;
    int xDeadzone, yDeadzone;

    if ((pad->buttons.mode >> 4) == 0x07) {
        switch (gXSensitivity) {
            case 0:
                xDeadzone = 100;
                break;
            case 1:
                xDeadzone = 80;
                break;
            case 2:
                xDeadzone = 60;
                break;
            default:
                xDeadzone = 80;
        }

        switch (gYSensitivity) {
            case 0:
                yDeadzone = 100;
                break;
            case 1:
                yDeadzone = 80;
                break;
            case 2:
                yDeadzone = 60;
                break;
            default:
                yDeadzone = 80;
        }

        if (pad->buttons.ljoy_h < 127 - xDeadzone)
            padData |= PAD_LEFT;
        else if (pad->buttons.ljoy_h > 127 + xDeadzone)
            padData |= PAD_RIGHT;

        if (pad->buttons.ljoy_v < 127 - yDeadzone)
            padData |= PAD_UP;
        else if (pad->buttons.ljoy_v > 127 + yDeadzone)
            padData |= PAD_DOWN;
    }

    return padData;
}

static int readPad(struct pad_data_t *pad)
{
    int rcode = 0, oldState, newState, ret, padsRead;
    u32 newpdata = 0;

    padsRead = 0;
    oldState = pad->state;
    newState = padGetState(pad->port, pad->slot);
    updatePadState(pad, newState);
    if ((oldState == PAD_STATE_DISCONN) && ((pad->state == PAD_STATE_STABLE) || (pad->state == PAD_STATE_FINDCTP1))) {
        // Pad just connected.
        LOG("PAD pad %d,%d connected\n", pad->port, pad->slot);
        pad->analogCapable = -1;
        pad->analogRetryDelay = 0;
        initializePad(pad);
    }
    // The pad may transit from any state to disconnected. So check only for the disconnected state.
    else if ((oldState != PAD_STATE_DISCONN) && (pad->state == PAD_STATE_DISCONN)) {
        LOG("PAD pad %d,%d disconnected\n", pad->port, pad->slot);
        pad->analogCapable = -1;
        pad->analogRetryDelay = 0;
    }

    if ((pad->state == PAD_STATE_STABLE) || (pad->state == PAD_STATE_FINDCTP1)) {
        // pad is connected. Read pad button information.
        ret = padRead(pad->port, pad->slot, &pad->buttons); // port, slot, buttons

        if (ret != 0) {
            newpdata = 0xffff ^ pad->buttons.btns;
            padsRead++;

            if ((pad->buttons.mode >> 4) == 0x07) {
                pad->analogCapable = 1;
                pad->analogRetryDelay = 0;
            } else if (pad->analogCapable != 0) {
                // freepad can temporarily return a pad to digital mode while recovering from a read error.
                // Retry forever with a backoff; a real digital-only controller is disabled once its non-empty
                // mode table proves that DualShock mode is absent.
                if (pad->analogRetryDelay > 0) {
                    pad->analogRetryDelay--;
                } else {
                    gDiag.padSelfHeal++; // PAD HUD SH: analog self-heal re-init attempts
                    initializePad(pad);
                    pad->analogRetryDelay = PAD_ANALOG_RETRY_DELAY;
                }
            }
        }
    }

#ifdef PADEMU
    if (ds34bt_get_status(pad->port) & DS34BT_STATE_RUNNING) {
        ret = ds34bt_get_data(pad->port, (u8 *)&pad->buttons.btns);
        ds34bt_set_rumble(pad->port, 0, 0);
        if (ret != 0) {
            newpdata |= 0xffff ^ pad->buttons.btns;
            padsRead++;
        }
    }

    if (ds34usb_get_status(pad->port) & DS34USB_STATE_RUNNING) {
        ret = ds34usb_get_data(pad->port, (u8 *)&pad->buttons.btns);
        ds34usb_set_rumble(pad->port, 0, 0);
        if (ret != 0) {
            newpdata |= 0xffff ^ pad->buttons.btns;
            padsRead++;
        }
    }
#endif
    if (padsRead > 0) {
        newpdata = readLeftJoy(pad, newpdata);

        if (newpdata != 0x0) // something
            rcode = 1;
        else
            rcode = 0;

        pad->oldpaddata = pad->paddata;
        pad->paddata = newpdata;

        // merge into the global vars
        paddata |= pad->paddata;
    }

    return rcode;
}

/** Returns delay (in miliseconds) specified for the given key.
 * @param id The button id
 * @param repeat Boolean value specifying if we want initial key delay (0) or the repeat key delay (1)
 * @return the delay to the next key event
 */
static int getKeyDelay(int id, int repeat)
{
    int delay = paddelay[id - 1];

    // if not in repeat, the delay is enlarged
    if (!repeat)
        delay *= 3;

    return delay;
}

/** polling method. Call every frame. */
int readPads()
{
    int i;
    oldpaddata = paddata;
    paddata = 0;

    // in ms.
    u32 newtime = cpu_ticks() / CLOCKS_PER_MILISEC;
    time_since_last = newtime - curtime;
    curtime = newtime;

    int rslt = 0;

    for (i = 0; i < pad_count; ++i) {
        rslt |= readPad(&pad_data[i]);
    }

    for (i = 0; i < 16; ++i) {
        if (getKeyPressed(i + 1))
            delaycnt[i] -= time_since_last;
        else
            delaycnt[i] = getKeyDelay(i + 1, 0);
    }

    return rslt;
}

/** Key getter with key repeats.
 * @param id The button ID
 * @return nonzero if button is being pressed just now
 */
int getKey(int id)
{
    if ((id <= 0) || (id >= 17))
        return 0;

    int kid = id - 1;

    // either the button was not pressed this frame, then reset counter and return
    // or it was, then handle the repetition
    if (getKeyOn(id)) {
        delaycnt[kid] = getKeyDelay(id, 0);
        KeyPressedOnce = 1;
        DisableCron = 1;
        return 1;
    }

    if (!getKeyPressed(id))
        return 0;

    if (delaycnt[kid] <= 0) {
        delaycnt[kid] = getKeyDelay(id, 1);
        KeyPressedOnce = 1;
        DisableCron = 1;
        return 1;
    }

    return 0;
}

/** Detects key-on event. Returns true if the button was not pressed the last frame but is pressed this frame.
 * @param id The button ID
 * @return nonzero if button is being pressed just now
 */
int getKeyOn(int id)
{
    if ((id <= 0) || (id >= 17))
        return 0;

    // old v.s. new pad data
    int keyid = keyToPad[id];

    return (paddata & keyid) && (!(oldpaddata & keyid));
}

/** Detects key-off event. Returns true if the button was pressed the last frame but is not pressed this frame.
 * @param id The button ID
 * @return nonzero if button is being released
 */
int getKeyOff(int id)
{
    if ((id <= 0) || (id >= 17))
        return 0;

    // old v.s. new pad data
    int keyid = keyToPad[id];

    return (!(paddata & keyid)) && (oldpaddata & keyid);
}

/** Returns true (nonzero) if the button is currently pressed
 * @param id The button ID
 * @return nonzero if button is being held
 */
int getKeyPressed(int id)
{
    if ((id <= 0) || (id >= 17))
        return 0;

    // old v.s. new pad data
    int keyid = keyToPad[id];

    return (paddata & keyid);
}

/** Sets the delay to wait for button repetition event to occur.
 * @param button The button ID
 * @param btndelay The button delay (in query count)
 */
void setButtonDelay(int button, int btndelay)
{
    if ((button <= 0) || (button >= 17))
        return;

    paddelay[button - 1] = btndelay;
}

int getButtonDelay(int button)
{
    if ((button <= 0) || (button >= 17))
        return 0;

    return paddelay[button - 1];
}

/** Unloads a single pad.
 * @see unloadPads */
static void unloadPad(struct pad_data_t *pad)
{
    padPortClose(pad->port, pad->slot);
}

/** Unloads all pads. Use to terminate the usage of the pads. */
void unloadPads()
{
    int i;

    for (i = 0; i < pad_count; ++i)
        unloadPad(&pad_data[i]);

    padEnd();
}

/** Tries to start a single pad.
 * @param pad The pad data holding structure
 * @return 0 Error, != 0 Ok */
static int startPad(struct pad_data_t *pad)
{
    int newState;

    if (padPortOpen(pad->port, pad->slot, pad->padBuf) == 0) {
        return 0;
    }

    pad->analogCapable = -1;
    pad->analogRetryDelay = 0;
    // Seed the PAD HUD fields to "unknown" so a pre-init read of the diag line can't be mistaken
    // for a latched digital-only verdict (AC:0) or an empty mode table (md:0).
    gDiag.padAnalogCapable = -1;
    gDiag.padModes = -1;
    gDiag.padMode0 = -1;
    gDiag.padMode1 = -1;
    initializePad(pad);

    newState = waitPadReady(pad);
    updatePadState(pad, newState);
    return 1;
}

/** Starts all pads.
 * @return Count of dual shock compatible pads. 0 if none present. */
int startPads()
{
    // scan for pads that exist... at least one has to be present
    pad_count = 0;

    int maxports = padGetPortMax();

    int port; // 0 -> Connector 1, 1 -> Connector 2
    int slot; // Always zero if not using multitap

    for (port = 0; port < maxports; ++port) {
        int maxslots = padGetSlotMax(port);

        for (slot = 0; slot < maxslots && pad_count < MAX_PADS; ++slot) {

            struct pad_data_t *cpad = &pad_data[pad_count]; /* guard: pad_count < MAX_PADS asserted above */

            cpad->port = port;
            cpad->slot = slot;
            cpad->state = PAD_STATE_DISCONN;

            if (startPad(cpad))
                ++pad_count;
        }

        if (pad_count >= MAX_PADS)
            break; // enough already!
    }

    int n;
    for (n = 0; n < 16; ++n) {
        delaycnt[n] = DEFAULT_PAD_DELAY;
        paddelay[n] = DEFAULT_PAD_DELAY;
    }

    return pad_count;
}

void padStoreSettings(int *buffer)
{
    int i;

    for (i = 0; i < 16; i++)
        buffer[i] = paddelay[i];
}


void padRestoreSettings(int *buffer)
{
    int i;

    for (i = 0; i < 16; i++)
        paddelay[i] = buffer[i];
}
