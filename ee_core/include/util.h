/*
  Copyright 2009-2010, Ifcaro, jimmikaelkael & Polo
  Copyright 2006-2008 Polo
  Licenced under Academic Free License version 3.0
  Review Open-Ps2-Loader README & LICENSE files for further details.

  Some parts of the code are taken from HD Project by Polo
*/

#ifndef UTIL_H
#define UTIL_H

#include <tamtypes.h>

void _strcpy(char *dst, const char *src);
void _strcat(char *dst, const char *src);
int _strncmp(const char *s1, const char *s2, int length);
int _strcmp(const char *s1, const char *s2);
void set_ipconfig(void);
u32 *find_pattern_with_mask(u32 *buf, unsigned int bufsize, const u32 *pattern, const u32 *mask, unsigned int len);
void CopyToIop(void *eedata, unsigned int size, void *iopptr);
void WipeUserMemory(void *start, void *end);
void delay(int count);

#endif /* UTIL */
