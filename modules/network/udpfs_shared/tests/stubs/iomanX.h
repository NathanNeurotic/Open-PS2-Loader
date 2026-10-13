/* Host stub: just enough of ps2sdk's iomanX device API for ministack_xchg.c. */
#ifndef IOMANX_H
#define IOMANX_H

#define IOP_DT_FS    0x00000010
#define IOP_DT_FSEXT 0x10000000

struct _iomanX_iop_device;

typedef struct _iomanX_iop_file
{
    int mode;
    int unit;
    struct _iomanX_iop_device *device;
    void *privdata;
} iomanX_iop_file_t;

/* 27 ops, in iomanX order (init ... devctl at 23 ... ioctl2); the source fills them positionally. */
typedef struct _iomanX_iop_device_ops
{
    void *op0;
    void *op1;
    void *op2;
    void *op3;
    void *op4;
    void *op5;
    void *op6;
    void *op7;
    void *op8;
    void *op9;
    void *op10;
    void *op11;
    void *op12;
    void *op13;
    void *op14;
    void *op15;
    void *op16;
    void *op17;
    void *op18;
    void *op19;
    void *op20;
    void *op21;
    void *op22;
    void *op23;
    void *op24;
    void *op25;
    void *op26;
} iomanX_iop_device_ops_t;

typedef struct _iomanX_iop_device
{
    const char *name;
    unsigned int type;
    unsigned int version;
    const char *desc;
    iomanX_iop_device_ops_t *ops;
} iomanX_iop_device_t;

int AddDrv(iomanX_iop_device_t *device);
int DelDrv(const char *name);

#endif
