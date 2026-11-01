#ifndef HOST_THSEMAP
#define HOST_THSEMAP
typedef struct
{
    int attr, option, initial, max;
} iop_sema_t;
static inline int CreateSema(iop_sema_t *s)
{
    (void)s;
    return 1;
}
static inline int WaitSema(int s)
{
    (void)s;
    return 0;
}
static inline int SignalSema(int s)
{
    (void)s;
    return 0;
}
#endif
static inline int DeleteSema(int s)
{
    (void)s;
    return 0;
}
#ifndef HOST_ISIGNALSEMA
#define HOST_ISIGNALSEMA
static inline int iSignalSema(int s)
{
    (void)s;
    return 0;
}
#endif
