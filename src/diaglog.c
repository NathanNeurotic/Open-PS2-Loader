/*
  The hardware log and DIAG.TXT, ported from RIPPS2 build 115 (akilluminati47/RIPPS2, ripps2status.c).
  See include/diaglog.h.
*/

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <kernel.h>

#include "include/opl.h"
#include "include/config.h"
#include "include/pad.h"
#include "include/diaglog.h"

#define DIAG_SIZE (16 * 1024)

static char diagRing[DIAG_SIZE];
static int diagHead = 0, diagWrapped = 0;

void diagLog(const char *fmt, ...)
{
    char line[224];
    va_list ap;
    clock_t now = clock();
    int n, i, on;

    n = snprintf(line, sizeof(line), "%5d.%02d  ", (int)(now / CLOCKS_PER_SEC), (int)(now % CLOCKS_PER_SEC * 100 / CLOCKS_PER_SEC));
    va_start(ap, fmt);
    vsnprintf(line + n, sizeof(line) - n - 2, fmt, ap);
    va_end(ap);
    n = strlen(line);
    line[n++] = '\r';
    line[n++] = '\n';
    // DIntr says whether interrupts were on, so a caller that already turned them off keeps them off
    on = DIntr();
    for (i = 0; i < n; i++) {
        diagRing[diagHead++] = line[i];
        if (diagHead == DIAG_SIZE) {
            diagHead = 0;
            diagWrapped = 1;
        }
    }
    if (on)
        EIntr();
}

int diagCopy(char *out, int size, int *wrapped)
{
    int len, h, w, on, skip = 0;

    on = DIntr();
    h = diagHead;
    w = diagWrapped;
    len = w ? DIAG_SIZE : h;
    if (len > size) { // keep the newest lines
        skip = len - size;
        len = size;
    }
    if (w) {
        int start = (h + skip) % DIAG_SIZE, first = DIAG_SIZE - start;
        if (first > len)
            first = len;
        memcpy(out, diagRing + start, first);
        memcpy(out + first, diagRing, len - first);
    } else
        memcpy(out, diagRing + skip, len);
    if (on)
        EIntr();
    if (wrapped != NULL)
        *wrapped = w || skip > 0;
    return len;
}

int diagSave(const char *dir, char *path, int pathSize)
{
    static char copy[DIAG_SIZE];
    char head[400];
    u32 notReady = 0, empty = 0;
    int len, fd, ok, wrapped = 0;

    if (dir == NULL)
        dir = configGetDir();
    snprintf(path, pathSize, "%sDIAG.TXT", dir);
    len = diagCopy(copy, sizeof(copy), &wrapped);
    padGetFaultCounters(&notReady, &empty);
    snprintf(head, sizeof(head),
             "Open PS2 Loader %s diagnostics, %d s after boot\r\n"
             "longest run of missed pad reads: %u polls; of empty reads: %u polls\r\n"
             "MMCE: Game ID %s\r\n%s\r\n\r\n",
             OPL_VERSION, (int)(clock() / CLOCKS_PER_SEC), (unsigned)notReady, (unsigned)empty, gMMCEEnableGameID ? "on" : "off",
             wrapped ? "(the oldest lines have rolled out of the log)" : "");
    if ((fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666)) < 0)
        return 0;
    ok = write(fd, head, strlen(head)) == (int)strlen(head) && write(fd, copy, len) == len;
    close(fd);
    return ok;
}

void diagSaveBeforeLaunch(void)
{
    char path[300];
    const char *dir = configGetDir();

    if (!gEnableDebug || dir == NULL || !strncmp(dir, "mc", 2) || !strncmp(dir, "mmce", 4))
        return;
    diagSave(dir, path, sizeof(path));
}
