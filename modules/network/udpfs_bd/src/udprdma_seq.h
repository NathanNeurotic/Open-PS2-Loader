#ifndef UDPRDMA_SEQ_H
#define UDPRDMA_SEQ_H

#include <stdint.h>

/* ACKs are cumulative in the 12-bit sequence space. The forward half of the
 * ring covers the sent packet; the backward half is a stale ACK. A difference
 * of exactly 2048 is ambiguous and must not complete the send. */
static inline int udprdma_ack_covers(uint16_t acknowledged, uint16_t sent)
{
    return ((acknowledged - sent) & 0x0FFFu) < 0x0800u;
}

#endif
