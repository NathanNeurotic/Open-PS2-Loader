#ifndef __RAPOPSLAUNCH_H__
#define __RAPOPSLAUNCH_H__
#ifdef RETROACHIEVEMENTS
/* Remove only an owned module: 0 absent/removed, -1 user file, -2 I/O. */
int raPopsRemoveModule(const char *root);
/* Prepare only after the source and POPStarter launch paths are validated. */
int raPopsPrepare(const char *root, const char *watchRoot, const char *vcdPath, int slotFree);
#endif
#endif
