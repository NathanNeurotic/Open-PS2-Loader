#ifndef __DISCSUPPORT_H
#define __DISCSUPPORT_H

int discCheckBusy(void);
int discCheckSupportDeferred(void);
void discLaunch(int (*progress)(void));

#endif
