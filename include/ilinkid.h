#ifndef OPL_ILINKID_H
#define OPL_ILINKID_H

#include <tamtypes.h>
#include <string.h>

/* Display order is byte order. Zero selects the real console, as in Neutrino.
 * Always clear the output, including on malformed input or the next launch. */
static inline int oplParseILinkID(const char *text, u8 id[8])
{
    u8 parsed[8], any = 0;
    int i;
    memset(id, 0, 8);
    if (text == NULL || text[0] == '\0')
        return 0;
    if (strlen(text) != 16)
        return -1;
    for (i = 0; i < 16; i++) {
        unsigned char c = (unsigned char)text[i];
        int nibble;
        if (c >= '0' && c <= '9')
            nibble = c - '0';
        else if (c >= 'a' && c <= 'f')
            nibble = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F')
            nibble = c - 'A' + 10;
        else
            return -1;
        if ((i & 1) == 0)
            parsed[i / 2] = (u8)(nibble << 4);
        else
            parsed[i / 2] |= (u8)nibble;
        any |= (u8)nibble;
    }
    memcpy(id, parsed, 8);
    return any != 0;
}

#endif
