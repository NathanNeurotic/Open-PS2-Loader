#include <stdio.h>
#include "udprdma_seq.h"

int main(void)
{
    static const struct
    {
        uint16_t acknowledged;
        uint16_t sent;
        int covers;
    } cases[] = {
        {42, 42, 1},
        {41, 42, 0}
        {0, 4095, 1}
        {4095, 0, 0}
        {2047, 0, 1}
        {2048, 0, 0}
        {2049, 0, 0}
        {4094, 4095, 0},
        {0, 0, 1},
        {4094, 0, 0},
        {1, 4094, 1},
        {0, 2048, 0},
        {2048, 2049, 0},
    };
    unsigned int i;

    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        int got = udprdma_ack_covers(cases[i].acknowledged, cases[i].sent);
        if (got != cases[i].covers) {
            fprintf(stderr, "ACK %u for send %u: got %d, want %d\n",
                    cases[i].acknowledged, cases[i].sent, got, cases[i].covers);
            return 1;
        }
    }
    return 0;
}
