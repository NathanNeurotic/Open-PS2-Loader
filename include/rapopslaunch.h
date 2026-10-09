#ifndef __RAPOPSLAUNCH_H__
#define __RAPOPSLAUNCH_H__
#ifdef RETROACHIEVEMENTS
/* Prepare only after the source and POPStarter launch paths are validated. */
int raPopsPrepare(const char *root, const char *watchRoot, const char *vcdPath, int slotFree);
#endif
#endif
