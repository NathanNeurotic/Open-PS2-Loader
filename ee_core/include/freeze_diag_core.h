/*
  In-game freeze report (INGAMEDIAG flavour only). Called from the IGR path in padhook.c:
    FreezeDiag_Begin     combo seen, IGR worker at priority 0, sampler has suspended game threads; then the
                         report is drawn on the TV (freeze_diag_screen.c), before anything asks the IOP
    FreezeDiag_FetchAndShutdown  replaces oplIGRShutdown(0): fetches the IOP's record, then sends
                                 the shutdown with a deadline (skipped if the IOP did not answer)
    FreezeDiag_Write     after the IGR IOP reboot; freezediag.irx writes mc0:/RIPTFRZ.TXT
*/

#ifndef FREEZE_DIAG_CORE_H
#define FREEZE_DIAG_CORE_H

#ifdef INGAMEDIAG

extern unsigned int g_freeze_diag_polls;
extern unsigned int g_freeze_diag_reset_failures;

void FreezeDiag_Begin(unsigned int libpad, unsigned int pad_state, unsigned int pad_frame, unsigned int trigger);
void FreezeDiag_FetchAndShutdown(void);
void FreezeDiag_Write(void);

#endif

#endif
