/*
  In-game freeze report writer (INGAMEDIAG flavour only).

  ee_core loads this once, after the IGR IOP reboot, with ROM SIO2MAN and MCMAN already loaded.
  argv[1] is the IOP address (eight hex digits) where ee_core copied its freeze_diag_report_t.
  This formats it with the same formatter the host test covers and writes mc0:/RIPTFRZ.TXT
  (mc1 if slot 1 fails). The work lives on the IOP because ee_core has no room for the
  formatter or the EE file client.
*/

#include "irx_imports.h"
#include "freeze_diag_report.h"

#define MODNAME "freezediag"
IRX_ID(MODNAME, 1, 1);

#ifndef FREEZEDIAG_BUILD
#define FREEZEDIAG_BUILD "unknown"
#endif

#define TEXT_CAP 4096

static unsigned int parse_hex8(const char *s)
{
    unsigned int v = 0;
    int i;

    for (i = 0; i < 8; i++) {
        char c = s[i];

        if (c >= '0' && c <= '9')
            v = (v << 4) | (unsigned int)(c - '0');
        else if (c >= 'A' && c <= 'F')
            v = (v << 4) | (unsigned int)(c - 'A' + 10);
        else if (c >= 'a' && c <= 'f')
            v = (v << 4) | (unsigned int)(c - 'a' + 10);
        else
            return 0;
    }
    return v;
}

static int write_report(const char *path, const char *text, int len)
{
    int fd, written;

    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC);
    if (fd < 0)
        return 0;
    written = write(fd, (void *)text, len);
    close(fd);
    return written == len;
}

int _start(int argc, char *argv[])
{
    const freeze_diag_report_t *report;
    char *text;
    int len;

    if (argc < 2 || argv[1] == NULL)
        return MODULE_NO_RESIDENT_END;
    report = (const freeze_diag_report_t *)parse_hex8(argv[1]);
    if (report == NULL)
        return MODULE_NO_RESIDENT_END;

    text = AllocSysMemory(ALLOC_FIRST, TEXT_CAP, NULL);
    if (text == NULL)
        return MODULE_NO_RESIDENT_END;

    len = freeze_diag_format(report, FREEZEDIAG_BUILD, text, TEXT_CAP);
    if (!write_report("mc0:/RIPTFRZ.TXT", text, len))
        write_report("mc1:/RIPTFRZ.TXT", text, len);

    FreeSysMemory(text);
    return MODULE_NO_RESIDENT_END;
}
