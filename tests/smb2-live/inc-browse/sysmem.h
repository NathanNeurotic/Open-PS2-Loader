#include <stddef.h>
#define ALLOC_FIRST 0
extern void *__libc_malloc(size_t);
extern void __libc_free(void *);
static inline void *AllocSysMemory(int m, int size, void *a)
{
    (void)m;
    (void)a;
    size_t *p = __libc_malloc(size + 16);
    if (!p)
        return NULL;
    p[0] = size;
    return (char *)p + 16;
}
static inline int FreeSysMemory(void *p)
{
    __libc_free((char *)p - 16);
    return 0;
}
static inline int QueryBlockSize(void *p) { return (int)((size_t *)((char *)p - 16))[0]; }
