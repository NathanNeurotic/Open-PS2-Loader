typedef struct
{
    unsigned int attr, option;
    int initial, max;
} iop_sema_t;
int CreateSema(iop_sema_t *s);
int DeleteSema(int s);
int WaitSema(int s);
int SignalSema(int s);
