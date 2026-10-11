#ifndef EE_CORE_RESET_ARG_BOUNDS_H
#define EE_CORE_RESET_ARG_BOUNDS_H

/* The intercepted SifResetIop command has a ten-byte loader prefix. The
 * copied payload is followed by NUL and "host0:" (seven bytes total). */
#define EE_RESET_PREFIX_BYTES 10
#define EE_RESET_SUFFIX_BYTES 7

static inline int eeResetPayloadLength(int packetLength, unsigned int packetCapacity, unsigned int commandCapacity)
{
    unsigned int payload;

    if (packetLength < EE_RESET_PREFIX_BYTES || (unsigned int)packetLength > packetCapacity || commandCapacity < EE_RESET_SUFFIX_BYTES)
        return -1;
    payload = (unsigned int)(packetLength - EE_RESET_PREFIX_BYTES);
    if (payload > commandCapacity - EE_RESET_SUFFIX_BYTES)
        return -1;
    return (int)payload;
}

#endif
