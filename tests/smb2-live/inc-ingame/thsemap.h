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
