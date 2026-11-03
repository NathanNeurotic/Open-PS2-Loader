#ifndef HOST_IOMANX
#define HOST_IOMANX
#include "tamtypes.h"
#define FIO_O_RDONLY 0x0001
#define FIO_O_WRONLY 0x0002
#define FIO_O_RDWR   0x0003
#define FIO_O_CREAT  0x0200
#define FIO_O_TRUNC  0x0400
#define FIO_O_EXCL   0x0800
#define FIO_S_IFREG  0x2000
#define FIO_S_IFDIR  0x1000
#define FIO_S_IRUSR  0x0100
#define FIO_S_IWUSR  0x0080
#define FIO_S_IXUSR  0x0040
#define IOP_DT_FS    0x10
#define IOP_DT_FSEXT 0x10000000
typedef struct
{
    unsigned int mode, attr, size;
    unsigned char ctime[8], atime[8], mtime[8];
    unsigned int hisize, p0, p1, p2, p3, p4, p5;
} iox_stat_t;
typedef struct
{
    iox_stat_t stat;
    char name[256];
    void *privdata;
} iox_dirent_t;
struct _iop_device;
typedef struct
{
    int mode, unit;
    struct _iop_device *device;
    void *privdata;
} iop_file_t;
typedef struct _iop_device_ops
{
    int (*init)(struct _iop_device *device);
    int (*deinit)(struct _iop_device *device);
    int (*format)(iop_file_t *f, const char *dev, const char *blockdev, void *arg, int arglen);
    int (*open)(iop_file_t *f, const char *name, int flags, int mode);
    int (*close)(iop_file_t *f);
    int (*read)(iop_file_t *f, void *ptr, int size);
    int (*write)(iop_file_t *f, void *ptr, int size);
    int (*lseek)(iop_file_t *f, int offset, int mode);
    int (*ioctl)(iop_file_t *f, int cmd, void *param);
    int (*remove)(iop_file_t *f, const char *name);
    int (*mkdir)(iop_file_t *f, const char *path, int mode);
    int (*rmdir)(iop_file_t *f, const char *path);
    int (*dopen)(iop_file_t *f, const char *path);
    int (*dclose)(iop_file_t *f);
    int (*dread)(iop_file_t *f, iox_dirent_t *buf);
    int (*getstat)(iop_file_t *f, const char *name, iox_stat_t *stat_);
    int (*chstat)(iop_file_t *f, const char *name, iox_stat_t *stat_, unsigned int statmask);
    int (*rename)(iop_file_t *f, const char *old, const char *new_);
    int (*chdir)(iop_file_t *f, const char *name);
    int (*sync)(iop_file_t *f, const char *dev, int flag);
    int (*mount)(iop_file_t *f, const char *fsname, const char *devname, int flag, void *arg, int arglen);
    int (*umount)(iop_file_t *f, const char *fsname);
    s64 (*lseek64)(iop_file_t *f, s64 offset, int whence);
    int (*devctl)(iop_file_t *f, const char *name, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen);
    int (*symlink)(iop_file_t *f, const char *old, const char *new_);
    int (*readlink)(iop_file_t *f, const char *path, char *buf, unsigned int buflen);
    int (*ioctl2)(iop_file_t *f, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen);
} iop_device_ops_t;
typedef struct _iop_device
{
    const char *name;
    unsigned int type, version;
    const char *desc;
    iop_device_ops_t *ops;
} iop_device_t;
int AddDrv(iop_device_t *d);
int DelDrv(const char *n);
#endif
