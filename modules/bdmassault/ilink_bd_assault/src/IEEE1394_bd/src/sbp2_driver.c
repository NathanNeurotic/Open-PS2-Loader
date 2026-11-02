#include <intrman.h>
#include <loadcore.h>
#include <stdio.h>
#include <sysclib.h>
#include <sysmem.h>
#include <thbase.h>
#include <thevent.h>
#include <thsemap.h>

#include "iLinkman.h"
#include "include/sbp2_disk.h"
#include "include/scsi.h"
#include "usbhdfsd-common.h"

// #define DEBUG  //comment out this line when not debugging
#include "include/module_debug.h"

#define MAX_DEVICES 5
static struct SBP2Device SBP2Devices[MAX_DEVICES];
static u8 *writeBuffer = NULL;

/* The target may still access an accepted ORB after a lost pointer ACK or a
 * timeout. Keep all remotely visible request storage resident. One command
 * owns the existing transfer buffer until its matching status arrives. */
static struct {
    struct CommandDescriptorBlock cdb;
    struct sbp2_pointer pointer;
    void *orb;
    struct SBP2Device *owner;
    int pending;
} command;
static int sbp2_io_sema;
#define SBP2_COMMAND_BUDGET_US (30 * 1000 * 1000)


/* Thread creation data. */
static iop_thread_t threadData = {
    TH_C,   /* attr */
    0,      /* option */
    NULL,   /* thread */
    0x1000, /* stacksize */
    0x30    /* priority */
};

// static unsigned long int iLinkBufferOffset, iLinkTransferSize;
static int sbp2_event_flag;

static void ieee1394_callback(int reason, unsigned long int offset, unsigned long int size);
static void iLinkIntrCBHandlingThread(void *arg);
static int ieee1394_SendManagementORB(int mode, struct SBP2Device *dev);
static int ieee1394_InitializeFetchAgent(struct SBP2Device *dev);
void free(void *buffer);
void *malloc(int NumBytes);

static void ieee1394_callback(int reason, unsigned long int offset, unsigned long int size)
{
    (void)offset;
    (void)size;
    if (reason == iLink_CB_BUS_RESET)
        SetEventFlag(sbp2_event_flag, BUS_RESET_COMPLETE);
}

/* Event flag creation data. */
static iop_event_t evfp = {
    2, /* evfp.attr=EA_MULTI */
    0, /* evfp.option */
    0  /* evfp.bits */
};

int iLinkIntrCBThreadID;
static int sbp2_get_max_lun(struct scsi_interface *scsi);
static int sbp2_queue_cmd(struct scsi_interface *scsi, const unsigned char *cmd, unsigned int cmd_len, unsigned char *data, unsigned int data_len, unsigned int data_wr);

int init_ieee1394DiskDriver(void)
{
    int i;
    iop_sema_t sema = {0, 0, 1, 1};

    for (i = 0; i < MAX_DEVICES; i++) {
        SBP2Devices[i].IsConnected = 0;
        SBP2Devices[i].nodeID = 0;
        SBP2Devices[i].trContext = (-1);

        SBP2Devices[i].scsi.priv = &SBP2Devices[i];
        SBP2Devices[i].scsi.name = "sd";
        SBP2Devices[i].scsi.max_sectors = XFER_BLOCK_SIZE / 512;
        SBP2Devices[i].scsi.get_max_lun = sbp2_get_max_lun;
        SBP2Devices[i].scsi.queue_cmd = sbp2_queue_cmd;
    }

    writeBuffer = malloc(XFER_BLOCK_SIZE);
    if (writeBuffer == NULL)
        return -1;
    sbp2_io_sema = CreateSema(&sema);
    if (sbp2_io_sema < 0) {
        free(writeBuffer);
        return -1;
    }
    sbp2_event_flag = CreateEventFlag(&evfp);
    if (sbp2_event_flag < 0) {
        DeleteSema(sbp2_io_sema);
        free(writeBuffer);
        return -1;
    }

    M_DEBUG("Starting threads..\n");

    threadData.thread = &iLinkIntrCBHandlingThread;
    iLinkIntrCBThreadID = CreateThread(&threadData);
    if (iLinkIntrCBThreadID < 0 || StartThread(iLinkIntrCBThreadID, NULL) < 0) {
        if (iLinkIntrCBThreadID >= 0)
            DeleteThread(iLinkIntrCBThreadID);
        DeleteEventFlag(sbp2_event_flag);
        DeleteSema(sbp2_io_sema);
        free(writeBuffer);
        return -1;
    }

    iLinkSetTrCallbackHandler(&ieee1394_callback);

    M_DEBUG("Threads created and started.\n");

    iLinkEnableSBus();
    return 0;
}

/* RiptOPL: how long a fresh driver keeps asking the drive for a login (#1018).
 *
 * Nothing in this driver ever logs out, and an IOP reset ends it without warning. POPSTARTER resets
 * the IOP before it loads this module from the memory card, so the drive still holds the exclusive
 * login of the driver that ran before (OPL's, or an earlier copy of this one) when this one brings
 * the bus back up. SBP-2 has the drive keep a login for 2^reconnect seconds after a bus reset in case
 * its owner reconnects: 1 s for the MANAGEMENT_ORB_RECONNECT(0) every login here asks for, longer on
 * bridges that round it up. Until it lets go, every new LOGIN is refused. The SDK gave up after 5
 * tries 200 ms apart (about 0.8 s), inside that hold, and nothing tries again until the next bus
 * reset, which POPSTARTER never causes, so the drive never attached for it; only Ember -- the one PS1
 * core that keeps the IOP -- booted from i.LINK. Keep asking at the same 200 ms pace until the hold
 * is certainly over. The budget is elapsed time, not a try count, so a drive that answers slowly
 * cannot stretch it. Same change as OPL's own copy of this driver (modules/ilink/IEEE1394_bd). */
#define SBP2_LOGIN_RETRY_US  (200 * 1000)
#define SBP2_LOGIN_BUDGET_US (5 * 1000 * 1000)

static u32 sbp2ElapsedUs(const iop_sys_clock_t *start)
{
    iop_sys_clock_t now, diff;
    u64 ticks;
    u32 sec, usec;

    GetSystemTime(&now);
    ticks = (((u64)now.hi << 32) | now.lo) - (((u64)start->hi << 32) | start->lo);
    diff.hi = (u32)(ticks >> 32);
    diff.lo = (u32)ticks;
    SysClock2USec(&diff, &sec, &usec);
    return sec * 1000000 + usec;
}


/* source 0 and 1 describe an ORB; 2 and 3 are unsolicited status. The length
 * distinguishes an empty FIFO from a source-0 completion. IOP addresses have
 * zero high 16 bits. Never consume another ORB's status as this one's reply. */
static int sbp2StatusReady(struct SBP2Device *dev, const void *orb)
{
    u32 status = dev->statusFIFO.status;
    return RESP_SRC(status) <= 1 && RESP_LEN(status) >= 1 &&
           (status & 0xffff) == 0 && dev->statusFIFO.ORB_low == (u32)orb &&
           (orb != &command.cdb || RESP_LEN(status) == 1 || dev->statusFIFO.data[0] != STATUS_UNWRITTEN);
}

static int ProcessStatus(struct SBP2Device *dev, const void *orb)
{
    u32 status = dev->statusFIFO.status;
    u32 detail = RESP_LEN(status) > 1 ? dev->statusFIFO.data[0] : 0;
    int sense = STATUS_SENSE_KEY(detail);
    if (sense == 0)
        sense = 1;
    if ((RESP_SBP_STATUS(status) == 0 || RESP_SBP_STATUS(status) == 0x0b) &&
        RESP_RESP(status) == 0 && !RESP_DEAD(status)) {
        if (RESP_LEN(status) == 1)
            return 0;
        /* A command may include a valid SCSI GOOD status block. Extended
         * status is not inherently an error; format 0/1 carries SAM status. */
        if (orb == &command.cdb && STATUS_SFMT(detail) <= 1 && STATUS_SAM(detail) == 0)
            return 0;
    }
    return -sense;
}

static int sbp2WaitStatus(struct SBP2Device *dev, const void *orb, u32 budget_us)
{
    iop_sys_clock_t start;
    u32 elapsed, delay;
    GetSystemTime(&start);
    while (dev->generation == iLinkGetGenerationNumber()) {
        if (sbp2StatusReady(dev, orb))
            return ProcessStatus(dev, orb);
        elapsed = sbp2ElapsedUs(&start);
        if (elapsed >= budget_us)
            break;
        delay = elapsed < 2000 ? 50 : (elapsed < 20000 ? 250 : 1000);
        if (delay > budget_us - elapsed)
            delay = budget_us - elapsed;
        DelayThread(delay);
    }
    return -1;
}

/* Called with sbp2_io_sema held. A timeout does not prove that DMA stopped.
 * A late matching status can retire the request; until then refuse reuse. */
static int sbp2CommandAvailable(void)
{
    if (command.pending && sbp2StatusReady(command.owner, command.orb)) {
        command.owner->fetchAgentNeedsReset = RESP_DEAD(command.owner->statusFIFO.status);
        command.pending = 0;
    }
    return !command.pending;
}

static int sbp2PublishCommand(struct SBP2Device *dev, u32 budget_us)
{
    int result;
    memset((void *)&dev->statusFIFO, 0, sizeof(dev->statusFIFO));
    // Wait for the first extended-status quadlet as well as its header.
    dev->statusFIFO.data[0] = STATUS_UNWRITTEN;
    command.pointer.low = (u32)command.orb;
    command.pointer.high = 0;
    command.pointer.NodeID = dev->InitiatorNodeID;
    command.owner = dev;
    command.pending = 1;

    /* Publish once. A transport error can follow target acceptance; resetting
     * and republishing the same request risks executing a write twice. */
    iLinkTrWrite(dev->trContext, dev->CommandBlockAgent_high,
                 dev->CommandBlockAgent_low + 0x08, &command.pointer, 8);
    result = sbp2WaitStatus(dev, command.orb, budget_us);
    if (sbp2StatusReady(dev, command.orb)) {
        dev->fetchAgentNeedsReset = RESP_DEAD(dev->statusFIFO.status);
        command.pending = 0;
    }
    return result;
}

static int initConfigureSBP2Device(struct SBP2Device *dev)
{
    iop_sys_clock_t start;

    /* RiptOPL: a retry after a failed warm-up keeps the login the drive already gave this
     * generation. Asking again would be refused: the drive keeps that login until a bus reset. */
    if (!dev->loggedIn) {
        GetSystemTime(&start);
        while (ieee1394_SendManagementORB(SBP2_LOGIN_REQUEST, dev) < 0) {
            /* RiptOPL: after a bus reset every further LOGIN here fails at once, so stop rather than
             * spin out the budget; the bus-reset thread starts the next attempt. */
            if (dev->generation != iLinkGetGenerationNumber() || sbp2ElapsedUs(&start) >= SBP2_LOGIN_BUDGET_US) {
                M_DEBUG("Failed to log into the SBP-2 device.\n");
                return -1;
            }
            DelayThread(SBP2_LOGIN_RETRY_US);
        }
    }

    if (ieee1394_InitializeFetchAgent(dev) < 0) {
        M_DEBUG("Error initializing the SBP-2 device's Fetch Agent.\n");
        return -2;
    }

    if (scsi_connect(&dev->scsi) < 0)
        return -3;

    M_DEBUG("Completed device initialization.\n");

    return 0;
}

static inline int initSBP2Disk(struct SBP2Device *dev)
{
    void *managementAgentAddr = NULL;
    unsigned int ConfigurationROMOffset, DirectorySize, i, LeafData, UnitDirectoryOffset;
    int result;

    UnitDirectoryOffset = 0;

    /* !! NOTE !! sce1394CrRead() reads data starting from the start of the target device's configuration ROM (0x400),
        and the offset and data to be read is specified in quadlets (Groups of 4 bytes)!!!!! */

    /* RiptOPL: the EUI-64 (bus info block quadlets 3 and 4, at 0x40C) names this drive in every bus
     * generation; node IDs can change at each reset. sbp2RetireOlderLogins matches drives by it. */
    if ((result = iLinkReadCROM(dev->nodeID, 3, 2, dev->eui64)) < 0) {
        M_DEBUG("Error reading the EUI-64. Error %d.\n", result);
        return (result);
    }

    M_DEBUG("Reading configuration ROM for the unit directory offset of node 0x%08x\n", dev->nodeID);

    /* Offset in quadlets: 0x14 / 4 = 5 */
    ConfigurationROMOffset = 5;

    if ((result = iLinkReadCROM(dev->nodeID, ConfigurationROMOffset, 1, &LeafData)) < 0) {
        M_DEBUG("Error reading the configuration ROM. Error %d.\n", result);
        return (result);
    }

    ConfigurationROMOffset++;

    /* Get the Unit Directory's offset from the root directory. */
    DirectorySize = LeafData >> 16;
    for (i = 0; i < DirectorySize; i++) {
        if ((result = iLinkReadCROM(dev->nodeID, ConfigurationROMOffset, 1, &LeafData)) < 0) {
            M_DEBUG("Error reading the configuration ROM. Error %d.\n", result);
            return (result);
        }

        if ((LeafData >> 24) == IEEE1394_CROM_UNIT_DIRECTORY) {
            UnitDirectoryOffset = ConfigurationROMOffset + (LeafData & 0x00FFFFFF);
            break;
        }

        ConfigurationROMOffset++;
    }
    if (i == DirectorySize)
        return -1;

    if ((result = iLinkReadCROM(dev->nodeID, UnitDirectoryOffset, 1, &LeafData)) < 0) {
        M_DEBUG("Error reading the configuration ROM. Error %d.\n", result);
        return (result);
    }

    DirectorySize = LeafData >> 16;
    for (i = 0; i < DirectorySize; i++) {
        /* Get the offset in the configuration ROM of the unit record. */
        if ((result = iLinkReadCROM(dev->nodeID, UnitDirectoryOffset + 1 + i, 1, &LeafData)) < 0) {
            M_DEBUG("Error reading the configuration ROM. Error %d.\n", result);
            return (result);
        }

        switch (LeafData >> 24) {
            /* Now get the address of the Management Agent CSR. */
            case IEEE1394_CROM_CSR_OFFSET:
                managementAgentAddr = (void *)(LeafData & 0x00FFFFFF); /* Mask off the bits that represent the Management Agent key. */
                M_DEBUG("managementAgentAddr=0x%08lx.\n", (u32)managementAgentAddr * 4);

                dev->ManagementAgent_low = (u32)managementAgentAddr * 4 + 0xf0000000;
                dev->ManagementAgent_high = 0x0000ffff;
                break;
            case IEEE1394_CROM_UNIT_CHARA:
                dev->mgt_ORB_timeout = (LeafData & 0x0000FF00) >> 8;
                dev->ORB_size = LeafData & 0x000000FF;
                M_DEBUG("mgt_ORB_timeout=%u; ORB_size=%u.\n", dev->mgt_ORB_timeout, dev->ORB_size);
                break;
            case IEEE1394_CROM_LOGICAL_UNIT_NUM:
                dev->LUN = LeafData & 0x0000FFFF;
                M_DEBUG("LUN=0x%08x.\n", dev->LUN);
                break;
        }
    }

    return 1;
}

/* RiptOPL: how long to wait before trying a drive that did not attach again (#1018).
 *
 * The SDK tried a drive only at a bus reset. A drive that refused or ignored its LOGIN for longer than
 * the login budget, or whose warm-up failed, then stayed detached until the next bus reset -- and
 * nothing in a running game causes one, so CDVDMAN or Neutrino waited for it forever. Keep trying
 * while the unit is on the bus: after 1 s, then 2 s and 4 s, then every 5 s. A bus reset ends the wait
 * at once and starts over. The wait polls, so it cannot sleep through a reset. */
#define SBP2_RETRY_FIRST_US (1000 * 1000)
#define SBP2_RETRY_MAX_US   (5 * 1000 * 1000)
#define SBP2_RETRY_POLL_US  (100 * 1000)
#define SBP2_RETRY_LIMIT    8 /* caps the counter only; retries never stop */

static u32 sbp2RetryDelayUs(unsigned int retries)
{
    u32 delay = SBP2_RETRY_FIRST_US;
    unsigned int i;

    for (i = 1; i < retries && delay < SBP2_RETRY_MAX_US; i++)
        delay *= 2;
    return delay < SBP2_RETRY_MAX_US ? delay : SBP2_RETRY_MAX_US;
}

/* Wait up to `us` for a bus reset. Returns 1 when one arrived (its event is consumed), 0 when not. */
static int sbp2WaitBusReset(u32 us)
{
    u32 bits, step;

    while (PollEventFlag(sbp2_event_flag, BUS_RESET_COMPLETE, WEF_AND | WEF_CLEAR, &bits) != 0) {
        if (us == 0)
            return 0;
        step = us < SBP2_RETRY_POLL_US ? us : SBP2_RETRY_POLL_US;
        DelayThread(step);
        us -= step;
    }
    return 1;
}

/* A bus reset ends every login: this driver never sends RECONNECT. Requests whose status has not
 * arrived keep their slots reserved (sbp2RetireOlderLogins releases them). */
static void sbp2BusReset(void)
{
    struct SBP2Device *dev;
    int i;

    WaitSema(sbp2_io_sema);
    for (i = 0; i < MAX_DEVICES; i++) {
        dev = &SBP2Devices[i];
        dev->IsConnected = dev->configuring = dev->loggedIn = 0;
        if (dev->trContext >= 0) {
            iLinkTrFree(dev->trContext);
            dev->trContext = -1;
        }
        if (dev->managementPending && sbp2StatusReady(dev, &dev->managementORB))
            dev->managementPending = 0;
    }
    sbp2CommandAvailable();
    SignalSema(sbp2_io_sema);
    /* BDM/FS unmount can take filesystem locks. Never hold the transport
     * mutex while calling it: an in-flight FS read may need that mutex. */
    for (i = 0; i < MAX_DEVICES; i++)
        scsi_disconnect(&SBP2Devices[i].scsi);
}

/* Bring up every SBP-2 unit on the bus that is not attached yet. Returns how many could not be
 * attached and are worth trying again without a bus reset. */
static int sbp2AttachUnits(void)
{
    int nNodes, i, j, nodeID, speed, generation, missing = 0;
    struct SBP2Device *dev, *slot;
    static const unsigned char PayloadSizeLookupTable[] = {7, 8, 9};

    nNodes = iLinkGetNodeCount();
    for (i = 0; i < nNodes; i++) {
        if ((nodeID = iLinkFindUnit(i, 0x0609e, 0x010483)) < 0)
            continue;
        WaitSema(sbp2_io_sema);
        sbp2CommandAvailable();
        generation = iLinkGetGenerationNumber();
        /* RiptOPL: a retry keeps the slot of its earlier attempt in this generation, so a late answer
         * to that attempt's LOGIN is still collected and an accepted login is reused, not refused.
         * Otherwise take the first slot whose remote storage nothing can still write. */
        dev = NULL;
        for (j = 0; j < MAX_DEVICES; j++) {
            slot = &SBP2Devices[j];
            if (slot->generation == generation && slot->nodeID == nodeID) {
                dev = slot;
                break;
            }
            if (dev == NULL && !slot->IsConnected && !slot->managementPending &&
                !(command.pending && command.owner == slot))
                dev = slot;
        }
        if (dev == NULL) {
            SignalSema(sbp2_io_sema);
            missing++;
            break;
        }
        if (dev->IsConnected) { /* attached already */
            SignalSema(sbp2_io_sema);
            continue;
        }
        dev->generation = generation;
        dev->nodeID = nodeID;
        dev->InitiatorNodeID = iLinkGetLocalNodeID();
        dev->ManagementAgent_high = dev->ManagementAgent_low = 0;
        dev->mgt_ORB_timeout = dev->ORB_size = dev->LUN = 0;
        speed = iLinkGetNodeMaxSpeed(nodeID);
        if (speed < 0 || speed > 2) { /* not a speed this driver can use */
            SignalSema(sbp2_io_sema);
            continue;
        }
        if (initSBP2Disk(dev) < 0) { /* a configuration ROM read failed: may pass next time */
            SignalSema(sbp2_io_sema);
            missing++;
            continue;
        }
        if (dev->ManagementAgent_low == 0) { /* no management agent: not a disk this driver can use */
            SignalSema(sbp2_io_sema);
            continue;
        }
        dev->trContext = iLinkTrAlloc(nodeID, speed);
        if (dev->trContext < 0) {
            SignalSema(sbp2_io_sema);
            missing++;
            continue;
        }
        speed = iLinkGetNodeTrSpeed(dev->trContext);
        if (speed < 0 || speed > 2) {
            iLinkTrFree(dev->trContext);
            dev->trContext = -1;
            SignalSema(sbp2_io_sema);
            continue;
        }
        dev->speed = speed;
        dev->max_payload = PayloadSizeLookupTable[speed];
        dev->configuring = 1;
        SignalSema(sbp2_io_sema);

        /* Warm-up submits normal SCSI commands, which acquire the mutex. */
        int result = initConfigureSBP2Device(dev);
        WaitSema(sbp2_io_sema);
        dev->configuring = 0;
        dev->IsConnected = result >= 0 && dev->generation == iLinkGetGenerationNumber();
        if (!dev->IsConnected) {
            iLinkTrFree(dev->trContext);
            dev->trContext = -1;
        }
        SignalSema(sbp2_io_sema);
        if (!dev->IsConnected) {
            scsi_disconnect(&dev->scsi);
            missing++;
        }
    }
    return missing;
}

/* Hardware event handling threads. */
static void iLinkIntrCBHandlingThread(void *arg)
{
    unsigned int retries = 0;
    (void)arg;
    while (1) {
        if (retries == 0) {
            WaitEventFlag(sbp2_event_flag, BUS_RESET_COMPLETE, WEF_AND | WEF_CLEAR, NULL);
            sbp2BusReset();
        } else if (sbp2WaitBusReset(sbp2RetryDelayUs(retries))) {
            retries = 0;
            sbp2BusReset();
        }
        if (sbp2AttachUnits() == 0)
            retries = 0;
        else if (retries < SBP2_RETRY_LIMIT)
            retries++;
    }
}

static int ieee1394_ResetFetchAgent(struct SBP2Device *dev)
{
    u32 dummy = 0;
    return iLinkTrWrite(dev->trContext, dev->CommandBlockAgent_high,
                        dev->CommandBlockAgent_low + 0x04, &dummy, 4);
}



static int ieee1394_InitializeFetchAgent(struct SBP2Device *dev)
{
    int result = -1;
    WaitSema(sbp2_io_sema);
    if (dev->generation != iLinkGetGenerationNumber() || !sbp2CommandAvailable() ||
        dev->ORB_size < sizeof(struct management_ORB) / 4)
        goto out;
    if (ieee1394_ResetFetchAgent(dev) < 0)
        goto out;
    dev->fetchAgentNeedsReset = 0;

    // No command data is transferred for a dummy ORB. Use the existing
    // staging allocation rather than reserving a worst-case 1020-byte dummy.
    command.orb = writeBuffer;
    memset(command.orb, 0, dev->ORB_size * 4);
    ((struct sbp2_ORB_pointer *)command.orb)->reserved = NULL_POINTER;
    ((struct management_ORB *)command.orb)->flags = ORB_NOTIFY | ORB_REQUEST_FORMAT(3);
    result = sbp2PublishCommand(dev, SBP2_COMMAND_BUDGET_US);
out:
    SignalSema(sbp2_io_sema);
    return result;
}

/* Called with sbp2_io_sema held, once dev's LOGIN succeeded. The drive granted an exclusive login,
 * so it held no other login at that moment: whatever earlier login of this drive a reserved slot's
 * unanswered LOGIN or command belonged to is gone, and SBP-2 aborts a released login's tasks, so the
 * drive will never write that storage again. Release it. Without this, a slot reserved by one lost
 * status stayed reserved for the whole session, and the shared command storage with it: every later
 * command, and every later fetch-agent setup, was refused until that status arrived, which it never
 * does once the drive has dropped the login. The EUI-64 tells this drive from other drives. */
static void sbp2RetireOlderLogins(struct SBP2Device *dev)
{
    struct SBP2Device *old;
    int i;

    for (i = 0; i < MAX_DEVICES; i++) {
        old = &SBP2Devices[i];
        if (old != dev) {
            if (old->IsConnected || old->configuring || (dev->eui64[0] == 0 && dev->eui64[1] == 0) ||
                old->eui64[0] != dev->eui64[0] || old->eui64[1] != dev->eui64[1])
                continue;
            old->managementPending = 0;
            old->loggedIn = 0;
        }
        /* The login granted just now has carried no command yet. */
        if (command.pending && command.owner == old)
            command.pending = 0;
    }
}

static int ieee1394_SendManagementORB(int mode, struct SBP2Device *dev)
{
    int result = -1;
    u32 budget;
    struct management_ORB *orb = &dev->managementORB;
    struct sbp2_login_response *response = &dev->loginResponse;

    WaitSema(sbp2_io_sema);
    if (mode != SBP2_LOGIN_REQUEST || dev->generation != iLinkGetGenerationNumber())
        goto out;
    if (dev->managementPending) {
        /* RiptOPL: the drive did not answer this LOGIN within its own management timeout (the whole
         * wait below). Write the pointer to the very same request again -- same ORB, same storage,
         * nothing cleared -- so a late answer to the first write still lands where this driver looks.
         * The SDK only polled, and ignored the write's result, so a pointer write the drive never took
         * left the LOGIN pending until the next bus reset (#1018). A drive still busy with the request
         * rejects the write (SBP-2: the management agent refuses a pointer while it is busy) and goes
         * on with the request. */
        if (!sbp2StatusReady(dev, orb))
            iLinkTrWrite(dev->trContext, dev->ManagementAgent_high, dev->ManagementAgent_low,
                         &dev->managementPointer, 8);
    } else {
        memset((void *)&dev->statusFIFO, 0, sizeof(dev->statusFIFO));
        memset(response, 0, sizeof(*response));
        memset(orb, 0, sizeof(*orb));
        orb->status_FIFO.low = (u32)&dev->statusFIFO;
        orb->flags = ORB_NOTIFY | MANAGEMENT_ORB_FUNCTION(mode) |
                     MANAGEMENT_ORB_RECONNECT(0) | MANAGEMENT_ORB_EXCLUSIVE(1) | MANAGEMENT_ORB_LUN(dev->LUN);
        orb->login.response.low = (u32)response;
        orb->length = MANAGEMENT_ORB_RESPONSE_LENGTH(sizeof(*response));
        dev->managementPointer.NodeID = dev->InitiatorNodeID;
        dev->managementPointer.high = 0;
        dev->managementPointer.low = (u32)orb;
        dev->managementPending = 1;
        iLinkTrWrite(dev->trContext, dev->ManagementAgent_high, dev->ManagementAgent_low,
                     &dev->managementPointer, 8);
    }

    budget = dev->mgt_ORB_timeout * 500000u;
    if (budget == 0)
        budget = 500000;
    if (budget > SBP2_LOGIN_BUDGET_US)
        budget = SBP2_LOGIN_BUDGET_US;
    result = sbp2WaitStatus(dev, orb, budget);
    if (sbp2StatusReady(dev, orb))
        dev->managementPending = 0;
    if (result == 0) {
        dev->CommandBlockAgent_high = response->command_block_agent.high;
        dev->CommandBlockAgent_low = response->command_block_agent.low;
        dev->loginID = response->login_ID;
        if (dev->CommandBlockAgent_low < 0xf0010000 ||
            (dev->CommandBlockAgent_high & 0xffff) != 0xffff)
            result = -1;
        else {
            dev->loggedIn = 1;
            sbp2RetireOlderLogins(dev);
        }
    }
out:
    SignalSema(sbp2_io_sema);
    return result;
}



static int sbp2_get_max_lun(struct scsi_interface *scsi)
{
    (void)scsi;

    return 0;
}

/* All internal destinations are quadlet aligned. Use one pass for the
 * common aligned sector/CDB path; callers handle unaligned or partial tails. */
static void sbp2CopySwapped(void *destination, const void *source, unsigned int nQuads)
{
    u32 *out = (u32 *)destination;
    const u32 *in = (const u32 *)source;
    unsigned int i;
    for (i = 0; i < nQuads; i++)
        out[i] = BSWAP32(in[i]);
}

static int sbp2_queue_cmd(struct scsi_interface *scsi, const unsigned char *cmd, unsigned int cmd_len, unsigned char *data, unsigned int data_len, unsigned int data_wr)
{
    struct SBP2Device *dev = (struct SBP2Device *)scsi->priv;
    struct CommandDescriptorBlock *cdb = &command.cdb;
    unsigned int nQuads;
    int result = -1;
    u32 *words;

    if (data_len > XFER_BLOCK_SIZE || cmd_len == 0 || cmd_len > sizeof(cdb->CDBs) ||
        (cmd_len & 3) != 0 || cmd == NULL || (data_len != 0 && data == NULL))
        return -1;

    WaitSema(sbp2_io_sema);
    if ((!dev->IsConnected && !dev->configuring) || dev->managementPending ||
        dev->generation != iLinkGetGenerationNumber() || !sbp2CommandAvailable())
        goto out;

    // A completed status with DEAD set stops the fetch agent. Retrying a SCSI
    // command without resetting it would wait for an ORB it will never fetch.
    if (dev->fetchAgentNeedsReset) {
        if (ieee1394_ResetFetchAgent(dev) < 0)
            goto out;
        dev->fetchAgentNeedsReset = 0;
    }
    memset(cdb, 0, sizeof(*cdb));
    cdb->misc = ORB_NOTIFY | CDB_MAX_PAYLOAD(dev->max_payload) | CDB_SPEED(dev->speed) |
                CDB_DATA_SIZE(data_len);
    // Disk reads make the target WRITE to IOP RAM; disk writes make it READ.
    cdb->misc |= data_wr ? CDB_DIRECTION(READ_TRANSACTION) : CDB_DIRECTION(WRITE_TRANSACTION);
    cdb->DataDescriptor.low = (u32)writeBuffer;
    cdb->DataDescriptor.NodeID = dev->InitiatorNodeID;
    cdb->NextOrb.reserved = NULL_POINTER;
    // Resident CDB/staging storage is aligned; caller buffers need not be.
    if (((u32)cmd & 3) == 0)
        sbp2CopySwapped(cdb->CDBs, cmd, cmd_len / 4);
    else {
        memcpy(cdb->CDBs, cmd, cmd_len);
        sbp2CopySwapped(cdb->CDBs, cdb->CDBs, cmd_len / 4);
    }

    words = (u32 *)writeBuffer;
    nQuads = data_len / 4;
    if (data_len & 3)
        words[nQuads] = 0; /* padding only; do not clear a whole read buffer */
    if (data_wr && data_len > 0) {
        if ((((u32)data | data_len) & 3) == 0)
            sbp2CopySwapped(writeBuffer, data, nQuads);
        else {
            memcpy(writeBuffer, data, data_len);
            sbp2CopySwapped(writeBuffer, writeBuffer, (data_len + 3) / 4);
        }
    }
    command.orb = cdb;
    result = sbp2PublishCommand(dev, scsi->timeout_us ? scsi->timeout_us : SBP2_COMMAND_BUDGET_US);
    if (result == 0 && !data_wr && data_len > 0) {
        if (((u32)data & 3) == 0) {
            // Convert into the caller only after completion, in one pass.
            sbp2CopySwapped(data, writeBuffer, nQuads);
            if (data_len & 3) {
                u32 tail = BSWAP32(words[nQuads]);
                memcpy(data + nQuads * 4, &tail, data_len & 3);
            }
        } else {
            sbp2CopySwapped(writeBuffer, writeBuffer, (data_len + 3) / 4);
            memcpy(data, writeBuffer, data_len);
        }
    }
out:
    SignalSema(sbp2_io_sema);
    return result;
}


void DeinitIEEE1394(void)
{
    TerminateThread(iLinkIntrCBThreadID);
    DeleteThread(iLinkIntrCBThreadID);
    DeleteEventFlag(sbp2_event_flag);
}

void *malloc(int NumBytes)
{
    int OldState;
    void *buffer;

    CpuSuspendIntr(&OldState);
    buffer = AllocSysMemory(ALLOC_FIRST, NumBytes, NULL);
    CpuResumeIntr(OldState);

    return buffer;
}

void free(void *buffer)
{
    int OldState;

    CpuSuspendIntr(&OldState);
    FreeSysMemory(buffer);
    CpuResumeIntr(OldState);
}
