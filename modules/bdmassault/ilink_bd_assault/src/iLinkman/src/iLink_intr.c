/*    iLink_intr.c
 *    Purpose:    Contains the functions related to interrupt event management/response, and functions that manage IEEE1394 read/write requests and responses.
 *
 *    Last Updated:    2012/02/24
 *    Programmer:    SP193
 */

#include <dmacman.h>
#include <sysmem.h>
#include <stdio.h>
#include <thevent.h>
#include <intrman.h>

#include "iLinkman.h"
#include "include/iLink_internal.h"

extern int IntrEventFlag;
extern unsigned short int LocalNodeID;
extern int NodeCapabilities;
extern int nNodes;
extern int GenerationNumber;
extern struct ILINKMemMap *ILINKRegisterBase;
extern struct DMAChannelRegBlock *iLinkDMACRegs;
extern void (*CallBackFunction)(int reason, unsigned int offset, unsigned int size);

extern unsigned int *ConfigurationROM;
extern unsigned int ConfigurationROMSize;

unsigned int *TargetBuffer, NodeData[63];
unsigned int LocalCachedIntr0Register;
static unsigned int ResponseLength;
static unsigned short int ResponseNodeID;
static unsigned char ResponseLabel, ResponseCode, ResponseActive;
static int ResponseGeneration;

void iLinkPrepareResponse(struct TransactionContextData *context, unsigned char label,
                          unsigned char code, void *buffer, unsigned int length)
{
    int state;
    CpuSuspendIntr(&state);
    TargetBuffer = buffer;
    ResponseLength = length;
    ResponseNodeID = context->NodeID;
    ResponseGeneration = context->GenerationNumber;
    ResponseLabel = label;
    ResponseCode = code;
    ResponseActive = 1;
    CpuResumeIntr(state);
}

void iLinkFinishRequest(void)
{
    int state;
    CpuSuspendIntr(&state);
    ResponseActive = 0;
    TargetBuffer = NULL;
    CpuResumeIntr(state);
}


unsigned char IsBusRoot = 1; /* Assume that the console is the root, in case this variable is polled before it was set correctly. */

static void NoResponseHandler(unsigned int header, volatile unsigned int *buffer, unsigned int nQuads)
{
    unsigned int i;

    (void)header;
    (void)buffer;

    DEBUG_PRINTF("NULL response handler called.\n");

    for (i = 0; i < nQuads; i++) { /* Flush the buffer. */
        unsigned int data;
        data = *buffer;
        (void)data;
#ifdef DEBUG_TTY_FEEDBACK
        DEBUG_PRINTF("Unhandled data: 0x%08x.\n", data);
#endif
    }
}

static void PHYPacketHandler(unsigned int header, volatile unsigned int *buffer, unsigned int nQuads)
{
    unsigned int data;

    DEBUG_PRINTF("Received PHY packet.\n");

    if (header == PHY_SELF_ID_PACKET) {
        data = header;
        nQuads++;
        while (nQuads-- > 0) {
            if (data == PHY_SELF_ID_PACKET) {
                DEBUG_PRINTF("Receiving SELFID packets...\n");
                nNodes = 0;
            } else if ((data != 1) && (data != 0xE)) {
                if ((data >> 30) == 2) { /* SELFID entry. */
                    DEBUG_PRINTF("SELFID received from Node 0x%04x. Speed: 0x%02x. Power: 0x%02x.\n", SELF_ID_NODEID(data), SELF_ID_SPEED(data), SELF_ID_POWER(data));
                    NodeData[nNodes] = data;
                    nNodes++;
                } else {
                    DEBUG_PRINTF("Unknown quad received in SELF-ID phase: 0x%08x.\n", data);
                }
            } else { /* End of SELF ID packet receival. */
                /* The local node ID should be already valid at this point in execution. */
                LocalNodeID = ILINKRegisterBase->NodeID >> 16;

                IsBusRoot = (ILINKRegisterBase->ctrl0 & iLink_CTRL0_Root) ? 1 : 0;

                DEBUG_PRINTF("Local Node ID: 0x%04x.\n", LocalNodeID);
                SetEventFlag(IntrEventFlag, iLinkEventGotSELFIDs);
                if (CallBackFunction != NULL)
                    CallBackFunction(iLink_CB_BUS_RESET, 0, 0);
            }

            data = *buffer;
        }
    } else if (header == PHY_CONFIG_PACKET) {
        data = *buffer;
        /* For monitoring only. It seems like the PHY will automatically configure itself with the data from the PHY packet. */
        /* if (PHY_CONFIG_R(data))
            iLinkPHY_SetRootBit(PHY_CONFIG_ROOT_ID(data) == (LocalNodeID & 0x3F));
        if (PHY_CONFIG_T(data))
            iLinkPHY_SetGapCount(PHY_CONFIG_GAP_CNT(data)); */
        if (PHY_CONFIG_T(data)) {
            DEBUG_PRINTF("gap count: %d.\n", PHY_CONFIG_GAP_CNT(data));
        }
    } else {
        DEBUG_PRINTF("DEBUG: Unknown PHY packet type: 0x%8x.\n", header);
        NoResponseHandler(header, buffer, nQuads);
    }
}

static void ResponseHandler(unsigned int header, volatile unsigned int *buffer, unsigned int nQuads)
{
    struct ieee1394_TrResponsePacketHdr response;
    unsigned int headerQuads, payloadQuads, length, i, j, count, value, flags = 0;
    unsigned char code = (header >> 4) & 0xf;
    int state;

    headerQuads = code == IEEE1394_TCODE_WRITE_RESPONSE ? 3 : 4;
    if (nQuads < headerQuads) {
        NoResponseHandler(header, buffer, nQuads);
        return;
    }
    response.header = header;
    for (i = 1; i < headerQuads; i++)
        ((unsigned int *)&response)[i] = *buffer;
    length = code == IEEE1394_TCODE_READB_RESPONSE ? response.LastField >> 16 : 0;
    payloadQuads = (length + 3) / 4;
    if (payloadQuads > nQuads - headerQuads) {
        NoResponseHandler(header, buffer, nQuads - (headerQuads - 1));
        return;
    }

    /* A timeout can precede a late response. Match the active request before
     * touching caller memory or waking it. Copy/retirement cannot preempt one
     * another: an error IRQ may otherwise return the caller halfway through. */
    CpuSuspendIntr(&state);
    if (ResponseActive && ResponseGeneration == GenerationNumber &&
        (response.header2 >> 16) == ResponseNodeID &&
        ((header >> 10) & 0x3f) == ResponseLabel && code == ResponseCode) {
        if (((response.header2 >> 12) & 0xf) != 0 ||
            (code == IEEE1394_TCODE_READB_RESPONSE && length != ResponseLength)) {
            LocalCachedIntr0Register |= iLink_INTR0_UResp;
            flags = iLinkEventRequestError;
        } else {
            if (code == IEEE1394_TCODE_READQ_RESPONSE)
                *TargetBuffer = BSWAP32(response.LastField);
            else if (code == IEEE1394_TCODE_READB_RESPONSE) {
                for (i = 0; i < payloadQuads; i++) {
                    value = *buffer;
                    count = length - i * 4;
                    if (count >= 4 && (((unsigned int)TargetBuffer & 3) == 0))
                        TargetBuffer[i] = value;
                    else {
                        if (count > 4)
                            count = 4;
                        for (j = 0; j < count; j++)
                            ((unsigned char *)TargetBuffer)[i * 4 + j] = ((unsigned char *)&value)[j];
                    }
                }
                payloadQuads = 0;
            }
            flags = iLinkEventDataReceived;
        }
        ResponseActive = 0;
        TargetBuffer = NULL;
    }
    for (i = 0; i < payloadQuads; i++)
        value = *buffer;
    value = *buffer; /* speed trailer */
    (void)value;
    if (flags != 0)
        SetEventFlag(IntrEventFlag, flags);
    CpuResumeIntr(state);
}

static void WriteRequestHandler(unsigned int header, volatile unsigned int *buffer, unsigned int nQuads)
{
    struct ieee1394_TrPacketHdr req;
    unsigned int headerQuads, payloadQuads, i, j, data, count;
    unsigned char rCode = 0;

    headerQuads = (((header >> 4) & 0xF) == IEEE1394_TCODE_WRITEQ) ? 3 : 4;
    if (nQuads < headerQuads) {
        NoResponseHandler(header, buffer, nQuads);
        return;
    }
    req.header = header;
    req.misc = 4 << 16;
    for (i = 1; i < headerQuads; i++)
        ((unsigned int *)&req)[i] = *buffer;
    req.misc >>= 16;
    payloadQuads = (req.misc + 3) / 4;
    if (payloadQuads > nQuads - headerQuads) {
        NoResponseHandler(header, buffer, nQuads - (headerQuads - 1));
        return;
    }

#ifdef REQ_CHECK_MEM_BOUNDARIES
    if ((req.offset_high & 0xFFFF) != 0 || req.offset_low == 0 ||
        req.offset_low >= 0x00200000 || req.misc > 0x00200000 - req.offset_low)
        rCode = 6;
#endif
    // Rejected writes must consume the same payload/trailer as accepted writes.
    for (i = 0; i < payloadQuads; i++) {
        data = *buffer;
        if (rCode == 0) {
            count = req.misc - i * 4;
            if (count > 4)
                count = 4;
            if (count == 4 && (req.offset_low & 3) == 0)
                ((unsigned int *)req.offset_low)[i] = data;
            else
                for (j = 0; j < count; j++)
                    ((unsigned char *)req.offset_low)[i * 4 + j] = ((unsigned char *)&data)[j];
        }
    }
    data = *buffer;
    SendResponse(req.offset_high >> 16, (header >> 16) >> 6, rCode,
                 (header >> 10) & 0x3F, IEEE1394_TCODE_WRITE_RESPONSE,
                 (data >> 16) & 0x7, NULL, 0);
    if (rCode == 0 && CallBackFunction != NULL)
        CallBackFunction(iLink_CB_WRITE_REQUEST, req.offset_low, req.misc);
}

struct ieee1394_TrCommonRdPktHdr
{
    unsigned int header;
    unsigned int offset_high;
    unsigned int offset_low;
};

struct ieee1394_TrBlockRdPacketHdr
{
    struct ieee1394_TrCommonRdPktHdr header;

    unsigned int nBytes;
    unsigned int trailer;
};

struct ieee1394_TrQuadRdPacketHdr
{
    struct ieee1394_TrCommonRdPktHdr header;

    unsigned int trailer;
};

static void ReadRequestHandler(unsigned int header, volatile unsigned int *buffer, unsigned int nQuads)
{
    unsigned int QuadsToRead, offset_low, offset_high, nBytes;
    unsigned int ReadReqHeader[5];
    unsigned int i;
    unsigned short int DestinationNodeID;
    unsigned char tCode, speed, rCode, tLabel;

    (void)nQuads;

    rCode = 0;
    DEBUG_PRINTF("Incoming read request. Header: 0x%08x; Buffer: 0x%p; nQuads: 0x%08x.\n", header, buffer, nQuads);

    /* Read in the header. */
    ReadReqHeader[0] = header;
    tCode = (header >> 4) & 0xF;
    if (tCode == IEEE1394_TCODE_READQ) {
        QuadsToRead = sizeof(struct ieee1394_TrQuadRdPacketHdr) >> 2;
        DEBUG_PRINTF("Quadlet");
    } else {
        QuadsToRead = sizeof(struct ieee1394_TrBlockRdPacketHdr) >> 2;
        DEBUG_PRINTF("Block");
    }

    if (nQuads < QuadsToRead - 1) {
        NoResponseHandler(header, buffer, nQuads);
        return;
    }
    for (i = 1; i < QuadsToRead; i++) {
        ReadReqHeader[i] = *buffer;
    }

    if (tCode == IEEE1394_TCODE_READB) {
        offset_low = BSWAP32(((struct ieee1394_TrCommonRdPktHdr *)ReadReqHeader)->offset_low);
        offset_high = BSWAP32(((struct ieee1394_TrCommonRdPktHdr *)ReadReqHeader)->offset_high);
        DestinationNodeID = BSWAP16((unsigned short int)offset_high);
    } else {
        offset_low = ((struct ieee1394_TrCommonRdPktHdr *)ReadReqHeader)->offset_low;
        offset_high = ((struct ieee1394_TrCommonRdPktHdr *)ReadReqHeader)->offset_high;
        DestinationNodeID = (unsigned short int)(offset_high >> 16);
    }

    if (tCode == IEEE1394_TCODE_READQ) {
        nBytes = 4;
        speed = (((struct ieee1394_TrQuadRdPacketHdr *)ReadReqHeader)->trailer >> 16) & 0x7;
    } else {
        nBytes = ((struct ieee1394_TrBlockRdPacketHdr *)ReadReqHeader)->nBytes >> 16;
        speed = (((struct ieee1394_TrBlockRdPacketHdr *)ReadReqHeader)->trailer >> 16) & 0x7;
    }

    DEBUG_PRINTF(" read request to 0x%08x %08x with length %u.\n", offset_high, offset_low, nBytes);

#ifdef REQ_CHECK_MEM_BOUNDARIES
    if (((offset_high & 0x0000FFFF) == 0x0000FFFF) && ((offset_low & 0xF0000000) == 0xF0000000)) {
#endif
        offset_low &= 0x0FFFFFFF;
        if ((offset_low - 0x400) < ConfigurationROMSize && nBytes <= ConfigurationROMSize - (offset_low - 0x400)) {
            offset_high = 0;
            offset_low = (unsigned int)ConfigurationROM + (offset_low - 0x400);
        }
#ifdef REQ_CHECK_MEM_BOUNDARIES
        else {
            DEBUG_PRINTF("Read request is beyond the range of the configuration ROM.\n");
            rCode = 6;
            nBytes = 0;
        }
    } else if ((offset_high & 0xFFFF) != 0 || offset_low >= 0x00200000 || offset_low == 0 || nBytes > 0x00200000 - offset_low) {
        DEBUG_PRINTF("Invalid read request.");
        rCode = 6;
        nBytes = 0;
    }
#endif

    tCode = (tCode == IEEE1394_TCODE_READQ) ? IEEE1394_TCODE_READQ_RESPONSE : IEEE1394_TCODE_READB_RESPONSE;
    tLabel = (header >> 10) & 0x3F;
    SendResponse(DestinationNodeID, DestinationNodeID >> 6, rCode, tLabel, tCode, speed, (unsigned int *)offset_low, nBytes >> 2);

    DEBUG_PRINTF("Response sent!2.\n");

    if (rCode == 0 && CallBackFunction != NULL)
        CallBackFunction(iLink_CB_READ_REQUEST, offset_low, nBytes);
}

const void *RequestHandlers[] = {
    &WriteRequestHandler, /*  0: write quadlet         */
    &WriteRequestHandler, /*  1: write block           */
    &ResponseHandler,     /*  2: write response        */
    &NoResponseHandler,   /*  3: reserved              */
    &ReadRequestHandler,  /*  4: read quadlet          */
    &ReadRequestHandler,  /*  5: read block            */
    &ResponseHandler,     /*  6: read quadlet response */
    &ResponseHandler,     /*  7: read block response   */
    &NoResponseHandler,   /*  8: cycle start           */
    &NoResponseHandler,   /*  9: lock request          */
    &NoResponseHandler,   /* 10: ISO/stream data       */
    &NoResponseHandler,   /* 11: lock response         */
    &NoResponseHandler,   /* 12: reserved              */
    &NoResponseHandler,   /* 13: reserved              */
    &PHYPacketHandler,    /* 14: PHY packet            */
    &NoResponseHandler    /* 15: reserved              */
};

int iLinkIntrHandler(void *arg)
{
    unsigned int Intr0, LocalCachedIntr1Register, EventFlagBitsToSet;
#ifdef REQ_CHECK_DMAC_STAT
    unsigned int i;
#endif

    (void)arg;

    while (1) {
        /* Acknowledge interrupts while determining which interrupt events have occurred. Some events need to be acknowledged as early as possible or they will prevent the hardware from working properly. */
        ILINKRegisterBase->intr0 = Intr0 = ILINKRegisterBase->intr0 & ILINKRegisterBase->intr0Mask;
        ILINKRegisterBase->intr1 = LocalCachedIntr1Register = ILINKRegisterBase->intr1 & ILINKRegisterBase->intr1Mask;

        if (!Intr0 && !LocalCachedIntr1Register)
            break;

        // Preserve errors until the outgoing request consumes them. The ISR's
        // final zero sample and unrelated receive interrupts must not erase them.
        LocalCachedIntr0Register |= Intr0 & (iLink_INTR0_InvAck | iLink_INTR0_STO | iLink_INTR0_AckMiss | iLink_INTR0_RetEx | iLink_INTR0_UResp);
        EventFlagBitsToSet = 0;

        DEBUG_PRINTF("iLink interrupt: 0x%08x 0x%08x\n", Intr0, LocalCachedIntr1Register);

        if (LocalCachedIntr1Register & iLink_INTR1_UTD)
            EventFlagBitsToSet |= iLinkEventDataSent;

#ifdef REQ_CHECK_DMAC_STAT
        if (Intr0 & iLink_INTR0_DRFR) {
            iDEBUG_PRINTF("Handling DBUF FIFO data...\n");

            for (i = 0; i < 3; i++) {
                iDEBUG_PRINTF("DMA Channel %d CHCR: 0x%08x MADR: 0x%08x DLEN: 0x%05x SLICE: 0x%03x\n", 13 + i, iLinkDMACRegs[i].chcr, iLinkDMACRegs[i].madr, iLinkDMACRegs[i].dlen, iLinkDMACRegs[i].slice);

                if ((i > 0) && !(iLinkDMACRegs[i].chcr & DMAC_CHCR_AR)) {
                    iLinkDMACRegs[i].chcr = 0;
                    switch (i) {
                        case 1:
                            ILINKRegisterBase->dmaCtrlSR0 = 0;
                            break;
                        case 2:
                            ILINKRegisterBase->dmaCtrlSR1 = 0;
                            break;
                    }

                    iDEBUG_PRINTF("DMAC Channel %d stalled. Flushing FIFOs and reseting PHTs.\n", 13 + i);

                    iLinkInitPHT();
                }
            }
        }
#endif

        if (Intr0 & iLink_INTR0_PhyRst) {
            iDEBUG_PRINTF("-=Bus reset start detected=-\n");

            GenerationNumber++;

            iLinkInitPHT();
            EventFlagBitsToSet |= (iLinkEventBusReady | iLinkEventBusReset | iLinkEventError | iLinkEventRequestError);

            iDEBUG_PRINTF("-=PHTs initialized=-\n");
        }

        if (Intr0 & iLink_INTR0_URx) {
            EventFlagBitsToSet |= iLinkEventURx;
        }

        if (Intr0 & (iLink_INTR0_InvAck | iLink_INTR0_STO | iLink_INTR0_AckMiss | iLink_INTR0_RetEx | iLink_INTR0_UResp)) {
            EventFlagBitsToSet |= iLinkEventError | iLinkEventRequestError;
            iDEBUG_PRINTF("-=Missing/invalid response detected=-\n");
        }

        /* For debugging purposes */
#ifdef REQ_CHECK_ERRORS
        if (Intr0 & iLink_INTR0_HdrErr) {
            iDEBUG_PRINTF("-=HdrErr=-\n");
        }

        if (Intr0 & iLink_INTR0_SntBsyAck) {
            iDEBUG_PRINTF("-=iLink_INTR0_SntBsyAck=-\n");
        }
#endif

        if (Intr0 & iLink_INTR0_PBCntR) {
            EventFlagBitsToSet |= iLinkEventDMATransEnd;
            iDEBUG_PRINTF("-=End of DMA transfer=-\n");
        }

        if (Intr0 & iLink_INTR0_CmdRst) {
            iDEBUG_PRINTF("-=CmdRst=-\n");
            iLinkPHYBusReset();
        }

        iSetEventFlag(IntrEventFlag, EventFlagBitsToSet);
    }

    return 1;
}
