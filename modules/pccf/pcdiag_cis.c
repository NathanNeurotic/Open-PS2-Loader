/* Diagnostic additions for the SCPH-10000 PC CARD investigation, 2026-09-30.
   Reads only the primary attribute CIS chain; links are reported, not followed.
   No register writes, ATA commands, allocation, or unbounded card addresses. */
#include "pcdiag_cis.h"

static const char *tuple_name(unsigned int code)
{
    switch (code) {
        case 0x01:
            return "DEVICE";
        case 0x06:
            return "LONGLINK_MFC";
        case 0x11:
            return "LONGLINK_A";
        case 0x12:
            return "LONGLINK_C";
        case 0x13:
            return "LINKTARGET";
        case 0x14:
            return "NO_LINK";
        case 0x15:
            return "VERS_1";
        case 0x18:
            return "JEDEC_A";
        case 0x1a:
            return "CONFIG";
        case 0x1b:
            return "CFTABLE_ENTRY";
        case 0x1c:
            return "DEVICE_OC";
        case 0x20:
            return "MANFID";
        case 0x21:
            return "FUNCID";
        case 0x22:
            return "FUNCE";
        default:
            return "other";
    }
}

static void describe(unsigned int code, const unsigned char *data,
                     unsigned int length, pcdiag_cis_trace_t trace,
                     pcdiag_cis_info_t *info)
{
    unsigned int i, n, address_bytes, mask_bytes, at;
    unsigned long base;
    char text[65];
    if (code == 0x20 && length >= 4) {
        trace("dev9: CIS decoded MANFID manufacturer=%04x card=%04x",
              (unsigned int)data[0] | ((unsigned int)data[1] << 8),
              (unsigned int)data[2] | ((unsigned int)data[3] << 8));
    } else if (code == 0x21 && length >= 2) {
        ++info->function_count;
        info->function = data[0];
        trace("dev9: CIS decoded FUNCID function=%02x (%s) sysinit=%02x",
              (unsigned int)data[0], data[0] == 4 ? "fixed disk" : "other",
              (unsigned int)data[1]);
    } else if (code == 0x15 && length >= 2) {
        trace("dev9: CIS decoded VERS_1 major=%u minor=%u; text uses | for NUL",
              (unsigned int)data[0], (unsigned int)data[1]);
        for (i = 2; i < length && data[i] != 0xff;) {
            n = 0;
            while (i < length && data[i] != 0xff && n < sizeof(text) - 1) {
                unsigned char c = data[i++];
                text[n++] = c == 0 ? '|' : (c >= 32 && c <= 126 ? c : '?');
            }
            text[n] = 0;
            trace("dev9: CIS VERS_1 text=%s", text);
        }
    } else if (code == 0x1a && length >= 2) {
        address_bytes = (data[0] & 3) + 1;
        mask_bytes = ((data[0] >> 2) & 15) + 1;
        if (length < 2 + address_bytes + mask_bytes) {
            info->malformed = 1;
            trace("dev9: CIS CONFIG malformed length=%u required=%u",
                  length, 2 + address_bytes + mask_bytes);
            return;
        }
        base = 0;
        for (i = 0; i < address_bytes; ++i)
            base |= (unsigned long)data[2 + i] << (i * 8);
        ++info->config_count;
        info->config_base = base;
        info->register_mask = data[2 + address_bytes];
        trace("dev9: CIS decoded CONFIG base_attribute=%08lx last_index=%u mask_bytes=%u COR_present=%u",
              base, (unsigned int)(data[1] & 0x3f), mask_bytes,
              (unsigned int)(data[2 + address_bytes] & 1));
    } else if (code == 0x1b && length >= 1) {
        at = 1;
        trace("dev9: CIS decoded CFTABLE index=%u default=%u interface_present=%u",
              (unsigned int)(data[0] & 0x3f), (unsigned int)((data[0] >> 6) & 1),
              (unsigned int)((data[0] >> 7) & 1));
        if (data[0] & 0x80) {
            if (at >= length) {
                info->malformed = 1;
                trace("dev9: CIS CFTABLE malformed: missing interface byte");
                return;
            }
            trace("dev9: CIS CFTABLE interface=%02x type=%u (%s)",
                  (unsigned int)data[at], (unsigned int)(data[at] & 15),
                  (data[at] & 15) == 0 ? "memory" :
                                         ((data[at] & 15) == 1 ? "IO" : "other"));
            if ((data[0] & 0x3f) == 0 && (data[at] & 15) == 0 &&
                length > at + 1)
                info->memory_index_zero = 1;
            ++at;
        }
        if (at < length)
            trace("dev9: CIS CFTABLE feature_byte=%02x; see raw payload for resources",
                  (unsigned int)data[at]);
        else {
            info->malformed = 1;
            trace("dev9: CIS CFTABLE malformed: missing feature byte");
        }
    } else if (code == 0x21 || code == 0x1a || code == 0x1b) {
        info->malformed = 1;
    }
}

int pcdiag_cis_dump_info(pcdiag_cis_read_t read_byte, void *context,
                         pcdiag_cis_trace_t trace, pcdiag_cis_info_t *info)
{
    static const char hex[] = "0123456789abcdef";
    unsigned char data[254];
    char line[16 * 3 + 1];
    unsigned int bus = 0, code, length, i, at, count, tuples = 0;
    pcdiag_cis_info_t empty = {0};
    *info = empty;
    trace("dev9: CIS DUMP BEGIN primary attribute chain; stride=2 bus_limit=%08lx tuple_limit=%u",
          (unsigned long)PCDIAG_CIS_BUS_LIMIT, PCDIAG_CIS_TUPLE_LIMIT);
    while (bus < PCDIAG_CIS_BUS_LIMIT) {
        code = read_byte(context, bus);
        bus += 2;
        if (code == 0)
            continue;
        if (code == 0xff) {
            info->complete = 1;
            trace("dev9: CIS DUMP END tuple at bus=%08lx tuples=%u",
                  (unsigned long)(bus - 2), tuples);
            return 0;
        }
        if (tuples >= PCDIAG_CIS_TUPLE_LIMIT) {
            trace("dev9: CIS DUMP STOP tuple limit at bus=%08lx", (unsigned long)(bus - 2));
            return -2;
        }
        if (bus >= PCDIAG_CIS_BUS_LIMIT) {
            trace("dev9: CIS DUMP STOP missing length at bus=%08lx", (unsigned long)(bus - 2));
            return -1;
        }
        length = read_byte(context, bus);
        bus += 2;
        if (length == 0xff) {
            trace("dev9: CIS DUMP END link=ff at bus=%08lx", (unsigned long)(bus - 4));
            return 0;
        }
        if (length > (PCDIAG_CIS_BUS_LIMIT - bus) / 2) {
            trace("dev9: CIS DUMP STOP payload outside bound at bus=%08lx length=%u",
                  (unsigned long)(bus - 4), length);
            return -1;
        }
        ++tuples;
        trace("dev9: CIS DUMP tuple=%u bus=%08lx code=%02x (%s) length=%u",
              tuples, (unsigned long)(bus - 4), code, tuple_name(code), length);
        for (i = 0; i < length; ++i)
            data[i] = read_byte(context, bus + i * 2);
        for (i = 0; i < length; i += 16) {
            count = length - i;
            if (count > 16)
                count = 16;
            for (at = 0; at < count; ++at) {
                line[at * 3] = hex[data[i + at] >> 4];
                line[at * 3 + 1] = hex[data[i + at] & 15];
                line[at * 3 + 2] = ' ';
            }
            line[count * 3 - 1] = 0;
            trace("dev9: CIS DATA bus=%08lx bytes=%s", (unsigned long)(bus + i * 2), line);
        }
        describe(code, data, length, trace, info);
        if (code == 0x06 || code == 0x11 || code == 0x12) {
            info->linked = 1;
            trace("dev9: CIS link recorded only; linked chain is not followed");
        }
        bus += length * 2;
    }
    trace("dev9: CIS DUMP STOP byte bound; END tuple was not found");
    return -2;
}

int pcdiag_cis_cf_candidate(const pcdiag_cis_info_t *info)
{
    return info->complete && !info->malformed && !info->linked &&
           info->function_count == 1 && info->function == 4 &&
           info->config_count == 1 && info->config_base == 0x200UL &&
           (info->register_mask & 1) && info->memory_index_zero;
}
