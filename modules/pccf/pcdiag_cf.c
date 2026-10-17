/* PC CARD DIAG 4, 2026-10-01.
   Observe the CF memory register map before any ATA commands are attempted.
   Wisi's DEV9C_PCMCIA.txt v01 gives conflicting interpretations of selector
   values 0 and 3. Treat them as candidates, not confirmed Common Memory.
   Card registers are never written. Data ports 0, 8, 9 and 0x400..0x7ff are
   excluded, so the diagnostic does not consume a sector/data transfer.
   Layout: Transcend CF133 manual, memory-mapped registers table (page 46).
   Bus width bit: PS2SDK ssbusc.h, ATYP bit 12 of the timing register. */
#include "pcdiag_cf.h"

int pcdiag_cf_probe(const pcdiag_cis_info_t *info, const pcdiag_cf_ops_t *ops,
                    void *context, pcdiag_cis_trace_t trace)
{
    static const unsigned int offsets8[] = {1, 2, 3, 4, 5, 6, 7, 0x0d, 0x0e, 0x0f};
    static const unsigned int offsets16[] = {2, 4, 6, 0x0c, 0x0e};
    static const unsigned int spaces[] = {0, 3};
    unsigned char config[4] = {0, 0, 0, 0}, bytes[10];
    unsigned short words[5];
    unsigned int sample, candidate, i, cor;

    if (!pcdiag_cis_cf_candidate(info)) {
        trace("dev9: CF PROBE SKIP: primary CIS lacks unambiguous fixed-disk / COR@0200 / memory-index-0 profile");
        return 1;
    }
    /* The owner has already selected attribute space with byte-wide timing. */
    for (i = 0; i < 4; ++i) {
        if (info->register_mask & (1U << i))
            config[i] = ops->read8(context, 0x200U + i * 2);
    }
    cor = config[0];
    trace("dev9: CF CONFIG mask=%02x COR@0200=%02x CSR@0202=%02x PRR@0204=%02x SCR@0206=%02x; absent registers shown as 00",
          info->register_mask, cor, (unsigned int)config[1],
          (unsigned int)config[2], (unsigned int)config[3]);
    if ((cor & 0x3f) != 0 || (cor & 0x80) != 0) {
        trace("dev9: CF PROBE SKIP: COR index=%u soft_reset=%u; no COR write is performed",
              cor & 0x3f, (cor >> 7) & 1);
        return 1;
    }

    trace("dev9: CF PROBE BEGIN: selector candidates=0,3; widths=8,16; samples=3; no card writes, no ATA commands");
    /* Allow CF to finish its reset after the original driver releases RESET. */
    ops->wait_ms(context, 500);
    for (sample = 1; sample <= 3; ++sample) {
        for (candidate = 0; candidate < 2; ++candidate) {
            ops->set_access(context, spaces[candidate], 8);
            for (i = 0; i < 10; ++i)
                bytes[i] = ops->read8(context, offsets8[i]);
            trace("dev9: CF READ8 sample=%u SPACE=%u ERR@01=%02x SC@02=%02x SN@03=%02x CL@04=%02x CH@05=%02x DH@06=%02x ST@07=%02x ERR@0d=%02x ALT@0e=%02x DA@0f=%02x",
                  sample, spaces[candidate], (unsigned int)bytes[0],
                  (unsigned int)bytes[1], (unsigned int)bytes[2],
                  (unsigned int)bytes[3], (unsigned int)bytes[4],
                  (unsigned int)bytes[5], (unsigned int)bytes[6],
                  (unsigned int)bytes[7], (unsigned int)bytes[8],
                  (unsigned int)bytes[9]);
            ops->set_access(context, spaces[candidate], 16);
            for (i = 0; i < 5; ++i)
                words[i] = ops->read16(context, offsets16[i]);
            trace("dev9: CF READ16 sample=%u SPACE=%u PAIR@02=%04x PAIR@04=%04x PAIR@06=%04x PAIR@0c=%04x PAIR@0e=%04x",
                  sample, spaces[candidate], (unsigned int)words[0],
                  (unsigned int)words[1], (unsigned int)words[2],
                  (unsigned int)words[3], (unsigned int)words[4]);
            trace("dev9: CF STATUS CANDIDATE sample=%u SPACE=%u ST8=%02x ALT8=%02x ST16_hi=%02x ALT16_lo=%02x; interpretation awaits hardware comparison",
                  sample, spaces[candidate], (unsigned int)bytes[6],
                  (unsigned int)bytes[8], (unsigned int)(words[2] >> 8),
                  (unsigned int)(words[4] & 0xff));
        }
        if (sample < 3)
            ops->wait_ms(context, 100);
    }
    trace("dev9: CF PROBE END: register reads only; sector access was not attempted");
    return 0;
}
