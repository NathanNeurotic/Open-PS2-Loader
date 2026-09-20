#include <stdio.h>
#include "../src/udprdma_seq.h"

int main(void)
{
    static const struct
    {
        uint16_t acknowledged;
        uint16_t sent;
        int covers;
    } cases[] = {
        {42, 42, 1},  /* current packet */
        {41, 42, 0},  /* delayed ACK from previous request */
        {0, 4095, 1}, /* forward across wrap */
        {4095, 0, 0}, /* stale across wrap */
        {2047, 0, 1}, /* last unambiguous forward value */
        {2048, 0, 0}, /* ambiguous half-ring */
        {2049, 0, 0}, /* backward half */
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
