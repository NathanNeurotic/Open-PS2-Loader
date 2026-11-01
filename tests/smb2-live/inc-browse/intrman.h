static inline int CpuSuspendIntr(int *s)
{
    *s = 0;
    return 0;
}
static inline int CpuResumeIntr(int s)
{
    (void)s;
    return 0;
}
