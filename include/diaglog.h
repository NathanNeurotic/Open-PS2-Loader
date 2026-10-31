#ifndef __OPL_DIAGLOG_H
#define __OPL_DIAGLOG_H

/*
  The hardware log, ported from RIPPS2 build 115 (akilluminati47/RIPPS2, ripps2diag.h).

  A release build has no console output, and a console run cannot be watched from a PC. So what matters on hardware
  (runs of missed pad reads, an MMCE card's Game ID switch and its wait, each launch, a settings save that failed)
  goes into a small ring in RAM, time-stamped. Drive Status > Save Diagnostics writes it to DIAG.TXT in the settings
  folder. Safe from any thread, never from an interrupt handler.
*/

void diagLog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

// The log so far, oldest line first, into out (at most size bytes, no terminator). Returns the length; *wrapped is
// set when the oldest lines have rolled out.
int diagCopy(char *out, int size, int *wrapped);

// DIAG.TXT in dir (the settings folder when NULL). 1 when written; the file's path goes into path either way.
int diagSave(const char *dir, char *path, int pathSize);

// Just before a launch, and only with Debug on: DIAG.TXT in the settings folder, so a launch that hangs still
// leaves its steps behind. Never to a memory card or an MMCE card, where a write could hold up the launch.
void diagSaveBeforeLaunch(void);

// Diagnostic builds: the early boot trace. From the first line of main() through the IOP reset, every module load
// and the boot stages up to the video setup, each step is printed on screen as it starts, so a boot that stops there
// leaves its last step on screen. bootTraceEnd() stops it where the video setup takes the GS over. Other builds
// compile it away.
#ifdef __OPLDIAG
void bootTrace(const char *step);
void bootTraceEnd(void);
#else
static inline void bootTrace(const char *step)
{
    (void)step;
}
static inline void bootTraceEnd(void)
{
}
#endif

#endif
