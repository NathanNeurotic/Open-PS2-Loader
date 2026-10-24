/*    iLink_TxRx.c
 *    Purpose:    Contains the functions that are used to transmit IEEE1394 response and request packets via the UBUF.
 *            Only quadlet reads and writes are supported by functions in this files.
 *
 *    Last Updated:    2012/02/21
 *    Programmer:    SP193
 */

#include <intrman.h>
#include <stdio.h>
#include <sysmem.h>
#include <thbase.h>
#include <thevent.h>
#include <thsemap.h>

#include "iLinkman.h"
#include "include/iLink_internal.h"

extern unsigned short int LocalNodeID;
extern int GenerationNumber;
extern int IntrEventFlag;

extern struct ILINKMemMap *ILINKRegisterBase;
extern struct DMAChannelRegBlock *iLinkDMACRegs;
extern unsigned *TargetBuffer;
extern unsigned int LocalCachedIntr0Register;
extern int UBUFTxSema;

static unsigned char NextRequestLabel;

static int iLinkSendData(struct TransactionContextData *trContext, unsigned int *header, unsigned int HeaderLength, unsigned int *payload, unsigned int PayloadLength);

static int iLinkSendData(struct TransactionContextData *trContext, unsigned int *header, unsigned int HeaderLength, unsigned int *payload, unsigned int PayloadLength)
{
    unsigned int i, *data;
    u32 FlagBits;

    WaitSema(UBUFTxSema);
    if (trContext != NULL) {
        LocalCachedIntr0Register = 0;
        ClearEventFlag(IntrEventFlag, ~(iLinkEventDataSent | iLinkEventDataReceived | iLinkEventError | iLinkEventRequestError));
    } else {
        // A target request can require a response while an outgoing PHT request
        // is pending. Do not consume that request's response/error events.
        ClearEventFlag(IntrEventFlag, ~(iLinkEventDataSent | iLinkEventError));
    }

    ILINKRegisterBase->ubufTransmitClear = 0;
    data = header;

    /* Transmit the header... */
    for (i = 0; i < HeaderLength; i++) {
        if ((trContext != NULL) && (trContext->GenerationNumber != GenerationNumber))
            goto generation_changed;

        ILINKRegisterBase->ubufTransmitNext = *data;
        data++;
    }

    /* Now transmit the payload. */
    if (PayloadLength > 0) {
        data = payload;
        for (i = 0; i < PayloadLength; i++) {
            if ((trContext != NULL) && (trContext->GenerationNumber != GenerationNumber))
                goto generation_changed;
            ILINKRegisterBase->ubufTransmitNext = *data;
            data++;
        }
    }

    ILINKRegisterBase->ubufTransmitLast = *(data - 1);

    DEBUG_PRINTF("Transmitting payload...\n");
    WaitEventFlag(IntrEventFlag, iLinkEventDataSent | iLinkEventError, WEF_OR, &FlagBits);

    if (FlagBits & iLinkEventError) {
        DEBUG_PRINTF("iLinkman: TX Error.\n");
    }

    SignalSema(UBUFTxSema);

    return ((FlagBits & iLinkEventError) ? (unsigned int)(-1) : PayloadLength);

generation_changed:
    // No packet was committed with ubufTransmitLast. Let the next sender clear
    // the partial FIFO and use its fresh transaction context.
    SignalSema(UBUFTxSema);
    return -1021;
}

void SendResponse(unsigned short int NodeID, unsigned short RcvdBusID, unsigned char rCode, unsigned char tLabel, unsigned char tCode, unsigned char speed, unsigned int *buffer, unsigned int nQuads)
{
    struct ieee1394_TrResponsePacketHdr ResponseHeader;
    unsigned int ResponseHeaderLength;

    ResponseHeaderLength = (tCode == IEEE1394_TCODE_READB_RESPONSE) ? 4 : 3;

    DEBUG_PRINTF("Sending response to: 0x%04x, RcvdBusID: 0x%04x, rcode: %d, Header length: %u, speed: 0x%04x. Payload length: 0x%08x.\n", NodeID, RcvdBusID, rCode, ResponseHeaderLength, speed, nQuads);
    DEBUG_PRINTF("tCode: 0x%02x\n", tCode);

    ResponseHeader.header = (((unsigned int)RcvdBusID) << 22) | (((unsigned int)speed) << 16) | (((unsigned int)tLabel) << 10) | (1 << 8) | (((unsigned int)tCode) << 4);
    ResponseHeader.header2 = (((unsigned int)NodeID) << 16) | (((unsigned int)rCode) << 12);
    ResponseHeader.reserved = 0;
    ResponseHeader.LastField = nQuads << 18;

    iLinkSendData(NULL, (unsigned int *)&ResponseHeader, ResponseHeaderLength, buffer, nQuads);
}

static iop_sys_clock_t Timeout = {
    0x8E9400, /* 0x800*125us / (1/36.5MHz) */
    0};

static unsigned int TimeoutCallbackFunction(void *argv)
{
    (void)argv;

    LocalCachedIntr0Register |= iLink_INTR0_STO;
    iSetEventFlag(IntrEventFlag, iLinkEventRequestError);
    return 0;
}

static int iLinkSync(unsigned int PayloadLength)
{
    u32 FlagBits;

    DEBUG_PRINTF("Payload transmitted. Now awaiting response...\n");

    SetAlarm(&Timeout, &TimeoutCallbackFunction, NULL);
    WaitEventFlag(IntrEventFlag, iLinkEventDataReceived | iLinkEventRequestError, WEF_OR, &FlagBits);

    // An IRQ error can beat the alarm; retire it before another transaction
    // reuses the event flag. A callback that already fired needs no cancellation.
    CancelAlarm(&TimeoutCallbackFunction, NULL);
    if (FlagBits & iLinkEventRequestError) {
        DEBUG_PRINTF("iLinkman: Split timeout.\n");
        if (!(LocalCachedIntr0Register & (iLink_INTR0_InvAck | iLink_INTR0_STO | iLink_INTR0_AckMiss | iLink_INTR0_RetEx | iLink_INTR0_UResp)))
            LocalCachedIntr0Register |= iLink_INTR0_STO;
    }

    DEBUG_PRINTF("Processing results...\n");

    if (LocalCachedIntr0Register & iLink_INTR0_InvAck)
        return (-1023);
    if (LocalCachedIntr0Register & iLink_INTR0_STO)
        return (-1024);
    if (LocalCachedIntr0Register & iLink_INTR0_AckMiss)
        return (-1025);
    if (LocalCachedIntr0Register & iLink_INTR0_RetEx)
        return (-1026);
    /* if (!(LocalCachedIntr0Register & iLink_INTR0_AckRcvd))
        return (-1); */
    /* Don't test for an acknowledge, as this somehow doesn't work right. :/ */

    return (FlagBits & iLinkEventRequestError) ? -1 : (int)PayloadLength;
}

int iLinkReadReq(struct TransactionContextData *trContext, unsigned short int offset_high, unsigned int offset_low, void *buffer, unsigned int nBytes)
{
    unsigned int nBytesToTransfer;
    struct ieee1394_TrPacketHdr TxHeader;
    int result;
    unsigned char tlabel, tCode;

    DEBUG_PRINTF("iLinkTrRead() 0x%08x %08x; nbytes: 0x%08x. Node: 0x%04x.\n", offset_high, offset_low, nBytes, trContext->NodeID);


    tlabel = NextRequestLabel = (NextRequestLabel + 1) % 63; /* 63 belongs to PHT 00. */
    tCode = IEEE1394_TCODE_READQ;
    iLinkPrepareResponse(trContext, tlabel, IEEE1394_TCODE_READQ_RESPONSE, buffer, nBytes);
    TxHeader.header = (((unsigned int)trContext->speed) << 16) | (((unsigned int)tlabel) << 10) | (1 << 8) | (((unsigned int)tCode) << 4);
    TxHeader.offset_high = (((unsigned int)trContext->NodeID) << 16) | offset_high;
    TxHeader.offset_low = offset_low;
    TxHeader.misc = nBytes << 16;

    nBytesToTransfer = sizeof(struct ieee1394_TrPacketHdr) - 4; /* Quadlet reads do not have the data length field. */

    if ((result = iLinkSendData(trContext, (unsigned int *)&TxHeader, nBytesToTransfer >> 2, NULL, 0)) >= 0) {
        result = iLinkSync(nBytesToTransfer);
        if (result < 0 && trContext->GenerationNumber != GenerationNumber)
            result = -1021;
    }

    return result;
}

int iLinkWriteReq(struct TransactionContextData *trContext, unsigned short int offset_high, unsigned int offset_low, void *buffer, unsigned int nBytes)
{
    unsigned int nBytesToTransfer;
    struct ieee1394_TrPacketHdr TxHeader;
    int result;
    unsigned char tlabel, tCode;

    DEBUG_PRINTF("iLinkTrWrite() 0x%08x %08x; nbytes: 0x%08x. Node: 0x%04x.\n", offset_high, offset_low, nBytes, trContext->NodeID);

    tlabel = NextRequestLabel = (NextRequestLabel + 1) % 63; /* 63 belongs to PHT 00. */
    tCode = IEEE1394_TCODE_WRITEQ;
    iLinkPrepareResponse(trContext, tlabel, IEEE1394_TCODE_WRITE_RESPONSE, NULL, 0);
    TxHeader.header = (((unsigned int)trContext->speed) << 16) | (((unsigned int)tlabel) << 10) | (1 << 8) | (((unsigned int)tCode) << 4);
    TxHeader.offset_high = (((unsigned int)trContext->NodeID) << 16) | offset_high;
    TxHeader.offset_low = offset_low;
    TxHeader.misc = nBytes << 16;

    nBytesToTransfer = sizeof(struct ieee1394_TrPacketHdr) - 4; /* Quadlet writes do not have the data length field. */

    if ((result = iLinkSendData(trContext, (unsigned int *)&TxHeader, nBytesToTransfer >> 2, buffer, nBytes >> 2)) >= 0) {
        result = iLinkSync(nBytesToTransfer);
        if (result < 0 && trContext->GenerationNumber != GenerationNumber)
            result = -1021;
    }

    return result;
}
